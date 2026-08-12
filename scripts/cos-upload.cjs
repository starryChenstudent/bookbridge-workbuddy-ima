#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const https = require('node:https');

const DEFAULT_TIMEOUT_MS = 300_000;
const REQUIRED = [
  'file',
  'secret-id',
  'secret-key',
  'token',
  'bucket',
  'region',
  'cos-key',
  'content-type',
  'start-time',
  'expired-time',
];

function parseArgs(argv) {
  const args = { _: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith('--')) {
      args._.push(token);
      continue;
    }
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) args[key] = true;
    else {
      args[key] = value;
      index += 1;
    }
  }
  return args;
}

function hmacSha1(key, data) {
  return crypto.createHmac('sha1', key).update(data).digest('hex');
}

function sha1(data) {
  return crypto.createHash('sha1').update(data).digest('hex');
}

function buildAuthorization({ secretId, secretKey, pathname, headers, startTime, expiredTime }) {
  const keyTime = `${startTime};${expiredTime}`;
  const signKey = hmacSha1(secretKey, keyTime);
  const headerKeys = Object.keys(headers).sort();
  const httpHeaders = headerKeys
    .map((key) => `${key.toLowerCase()}=${encodeURIComponent(headers[key])}`)
    .join('&');
  const httpString = `put\n${pathname}\n\n${httpHeaders}\n`;
  const stringToSign = `sha1\n${keyTime}\n${sha1(httpString)}\n`;
  const signature = hmacSha1(signKey, stringToSign);
  return [
    'q-sign-algorithm=sha1',
    `q-ak=${secretId}`,
    `q-sign-time=${keyTime}`,
    `q-key-time=${keyTime}`,
    `q-header-list=${headerKeys.map((key) => key.toLowerCase()).join(';')}`,
    'q-url-param-list=',
    `q-signature=${signature}`,
  ].join('&');
}

function validate(args) {
  const missing = REQUIRED.filter((key) => !String(args[key] || '').trim());
  if (missing.length) throw new Error(`缺少必要参数：${missing.map((key) => `--${key}`).join(', ')}`);
  const filePath = String(args.file);
  const stat = fs.statSync(filePath);
  if (!stat.isFile()) throw new Error('上传来源必须是普通文件');
  const timeout = Number(args.timeout || DEFAULT_TIMEOUT_MS);
  if (!Number.isFinite(timeout) || timeout < 10_000 || timeout > 3_600_000) {
    throw new Error('--timeout 必须在 10000 到 3600000 毫秒之间');
  }
  for (const key of ['bucket', 'region', 'cos-key']) {
    if (/\r|\n/.test(String(args[key]))) throw new Error('COS 元数据包含非法换行');
  }
  const hostname = `${args.bucket}.cos.${args.region}.myqcloud.com`;
  if (!/^[a-zA-Z0-9.-]+$/.test(hostname) || !hostname.endsWith('.myqcloud.com')) {
    throw new Error('COS 主机名无效');
  }
  return { filePath, stat, timeout, hostname };
}

function upload(args) {
  const { filePath, stat, timeout, hostname } = validate(args);
  const pathname = `/${String(args['cos-key']).replace(/^\/+/, '')}`;
  const headersToSign = { 'content-length': String(stat.size), host: hostname };
  const authorization = buildAuthorization({
    secretId: args['secret-id'],
    secretKey: args['secret-key'],
    pathname,
    headers: headersToSign,
    startTime: args['start-time'],
    expiredTime: args['expired-time'],
  });

  return new Promise((resolve, reject) => {
    const request = https.request(
      {
        hostname,
        port: 443,
        path: pathname,
        method: 'PUT',
        headers: {
          'Content-Type': args['content-type'],
          'Content-Length': stat.size,
          Authorization: authorization,
          'x-cos-security-token': args.token,
        },
        timeout,
      },
      (response) => {
        response.resume();
        response.on('end', () => {
          if (response.statusCode >= 200 && response.statusCode < 300) {
            resolve({ status: 'uploaded', status_code: response.statusCode, bytes: stat.size });
          } else reject(new Error(`COS 上传失败：HTTP ${response.statusCode}`));
        });
      },
    );
    request.on('timeout', () => request.destroy(new Error(`COS 上传超时：${timeout}ms`)));
    request.on('error', (error) => reject(new Error(`COS 上传失败：${error.message}`)));
    const input = fs.createReadStream(filePath);
    input.on('error', (error) => request.destroy(error));
    input.pipe(request);
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args._[0] === 'self-test') {
    const value = buildAuthorization({
      secretId: 'test-id',
      secretKey: 'test-secret',
      pathname: '/test-object',
      headers: { 'content-length': '10', host: 'bucket.cos.region.myqcloud.com' },
      startTime: '100',
      expiredTime: '200',
    });
    if (!value.includes('q-signature=') || value.includes('test-secret')) {
      throw new Error('COS 签名自检失败');
    }
    process.stdout.write('{"status":"ok","signing":"ok","upload_transport":"stream"}\n');
    return;
  }
  const result = await upload(args);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${JSON.stringify({ status: 'error', error: error.message || 'COS 上传失败' })}\n`);
    process.exitCode = 1;
  });
}

module.exports = { buildAuthorization, validate };
