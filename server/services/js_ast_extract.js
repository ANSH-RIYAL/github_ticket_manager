#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');

function parseFile(file) {
  const code = fs.readFileSync(file, 'utf8');
  const isTS = file.endsWith('.ts') || file.endsWith('.tsx');
  const ast = parser.parse(code, {
    sourceType: 'module',
    plugins: [
      'jsx',
      isTS ? 'typescript' : null,
      'classProperties',
      'exportDefaultFrom',
    ].filter(Boolean),
  });

  const exports = [];
  const functions = [];

  function getParams(node) {
    if (!node || !node.params) return [];
    return node.params.map(p => (p.name || p.left && p.left.name || 'param'));
  }

  const t = ast.types || {};

  const stack = [ast.program];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== 'object') continue;
    if (Array.isArray(node)) { node.forEach(n => stack.push(n)); continue; }

    if (node.type === 'ExportNamedDeclaration') {
      if (node.declaration && node.declaration.type === 'FunctionDeclaration') {
        const name = (node.declaration.id && node.declaration.id.name) || 'default';
        exports.push({ name, kind: 'function' });
        functions.push({ name, params: getParams(node.declaration), isExported: true });
      } else if (node.declaration && node.declaration.declarations) {
        for (const d of node.declaration.declarations) {
          const name = d.id && d.id.name;
          if (name) exports.push({ name, kind: 'const' });
        }
      } else if (node.specifiers) {
        for (const s of node.specifiers) {
          if (s.exported && s.exported.name) exports.push({ name: s.exported.name, kind: 'spec' });
        }
      }
    }
    if (node.type === 'ExportDefaultDeclaration') {
      exports.push({ name: 'default', kind: 'default' });
    }
    if (node.type === 'FunctionDeclaration') {
      const name = (node.id && node.id.name) || 'anon';
      functions.push({ name, params: getParams(node), isExported: false });
    }
    for (const k of Object.keys(node)) {
      const v = node[k];
      if (v && typeof v === 'object') stack.push(v);
    }
  }

  return { exports, functions };
}

function main() {
  const args = process.argv.slice(2);
  const idx = args.indexOf('--file');
  if (idx === -1 || !args[idx+1]) {
    console.log(JSON.stringify({ exports: [], functions: [] }));
    return;
  }
  const file = path.resolve(args[idx+1]);
  try {
    const out = parseFile(file);
    console.log(JSON.stringify(out));
  } catch (e) {
    console.log(JSON.stringify({ exports: [], functions: [] }));
  }
}

main();


