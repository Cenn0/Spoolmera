#!/usr/bin/env node
// Run from any directory: node frontend/scripts/check-i18n.mjs.
// This checks source literals, not runtime user data or arbitrary data flow.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import {
  ASTWithSource, Binary, BindingPipe, Call, Conditional, KeyedRead,
  LiteralArray, LiteralMap, LiteralPrimitive, NonNullAssert,
  ParenthesizedExpression, PropertyRead, RecursiveAstVisitor,
  TmplAstRecursiveVisitor, parseTemplate,
} from '@angular/compiler';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const attributes = new Set(['placeholder', 'title', 'aria-label']);
// Brand spellings, language autonyms, and the existing example integration alias
// intentionally retain their original spelling in both interface languages.
const originals = new Set([
  'FILAMENT', 'MANAGER', 'SPOOLMERA', 'Spoolmera',
  'Spoolman.', 'Moonraker / Klipper', 'OctoPrint', 'Home Assistant',
  'English', 'Deutsch', 'PLA', 'workshop-spoolman',
]);

function originalText(value) {
  const text = value.trim().replace(/\s+/g, ' ');
  if (!/\p{L}/u.test(text) || originals.has(text)) return true;
  // Measurements, tool numbers/prefixes, API examples, URLs, environment keys.
  if (/^(?:[\s\d.,:;·/×+−\-()%#=]|kg|mg|mm|cm|min|ms|MiB|GiB|MB|GB|°C|°F|g|m|s|h|T)+$/.test(text)) return true;
  if (/^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)(?:\s+\/\S+)?$/.test(text)) return true;
  if (/^(?:https?:\/\/\S+|\/[A-Za-z0-9_/?&=.#%<>:+-]+|SPOOLMERA_[A-Z0-9_]+)$/.test(text)) return true;
  return false;
}

function walkFiles(directory) {
  return fs.readdirSync(directory, {withFileTypes:true}).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? walkFiles(file) : [file];
  }).sort();
}

function location(label, text, offset = 0) {
  const before = text.slice(0, offset);
  return `${label}:${before.split('\n').length}:${offset - before.lastIndexOf('\n')}`;
}

function missingKey(key, catalog, report, where) {
  if (key.trim() && !catalog.has(key) && !originalText(key)) {
    report(`${where}: missing German translation for ${JSON.stringify(key)}`);
  }
}

function visibleText(text, report, where) {
  if (!originalText(text)) report(`${where}: untranslated visible text ${JSON.stringify(text.trim())}`);
}

function unwrapTs(node) {
  while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) ||
    ts.isTypeAssertionExpression(node) || ts.isSatisfiesExpression(node) || ts.isNonNullExpression(node))) {
    node = node.expression;
  }
  return node;
}

// Only output branches are messages. Comparing a state with 'pending' does not
// make that enum literal a displayed message or a required translation key.
function tsMessages(expression) {
  const node = unwrapTs(expression);
  if (!node) return [];
  if (ts.isStringLiteralLike(node)) return [{text:node.text, node}];
  if (ts.isConditionalExpression(node)) return [...tsMessages(node.whenTrue), ...tsMessages(node.whenFalse)];
  if (ts.isBinaryExpression(node) && [ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)) {
    return [...tsMessages(node.left), ...tsMessages(node.right)];
  }
  if (ts.isElementAccessExpression(node)) {
    const receiver = unwrapTs(node.expression);
    if (ts.isObjectLiteralExpression(receiver)) return receiver.properties.flatMap(property => ts.isPropertyAssignment(property) ? tsMessages(property.initializer) : []);
    if (ts.isArrayLiteralExpression(receiver)) return receiver.elements.flatMap(tsMessages);
  }
  return [];
}

function translatorCall(node, source) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return false;
  const method = node.expression;
  if (!['t', 'message'].includes(method.name.text)) return false;
  const receiver = method.expression;
  return ts.isIdentifier(receiver) && receiver.text === 'i18n' ||
    ts.isPropertyAccessExpression(receiver) && receiver.name.text === 'i18n' ||
    receiver.kind === ts.SyntaxKind.ThisKeyword && path.basename(source.fileName) === 'i18n.service.ts';
}

// Exported helpers also permit a small in-memory smoke check without adding
// fixture components to the application's source tree or a separate test suite.
export function auditTypeScript(text, label, catalog, report) {
  const source = ts.createSourceFile(label, text, ts.ScriptTarget.Latest, true);
  const templates = [];
  function visit(node) {
    if (translatorCall(node, source)) {
      for (const message of tsMessages(node.arguments[0])) {
        missingKey(message.text, catalog, report, location(label, text, message.node.getStart(source)));
      }
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'Component') {
      const metadata = unwrapTs(node.arguments[0]);
      if (metadata && ts.isObjectLiteralExpression(metadata)) {
        for (const property of metadata.properties) {
          if (!ts.isPropertyAssignment(property) || property.name.getText(source).replace(/^['"]|['"]$/g, '') !== 'template') continue;
          const template = unwrapTs(property.initializer);
          const where = location(label, text, property.getStart(source));
          if (ts.isStringLiteralLike(template)) templates.push({text:template.text, label:`${where} (inline template)`});
          else report(`${where}: inline templates must be static strings for the translation check`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return templates;
}

function angularTranslator(node) {
  return node instanceof Call && node.receiver instanceof PropertyRead &&
    ['t', 'message'].includes(node.receiver.name) &&
    node.receiver.receiver instanceof PropertyRead && node.receiver.receiver.name === 'i18n';
}

function angularMessages(ast, displayed = false) {
  if (ast instanceof ASTWithSource) return angularMessages(ast.ast, displayed);
  if (ast instanceof ParenthesizedExpression || ast instanceof NonNullAssert) return angularMessages(ast.expression, displayed);
  if (ast instanceof LiteralPrimitive) return typeof ast.value === 'string' ? [{text:ast.value, ast}] : [];
  if (ast instanceof Conditional) return [...angularMessages(ast.trueExp, displayed), ...angularMessages(ast.falseExp, displayed)];
  if (ast instanceof Binary && ['||', '??'].includes(ast.operation)) return [...angularMessages(ast.left, displayed), ...angularMessages(ast.right, displayed)];
  if (displayed && ast instanceof Binary && ast.operation === '+') return [...angularMessages(ast.left, true), ...angularMessages(ast.right, true)];
  if (ast instanceof KeyedRead && ast.receiver instanceof LiteralMap) return ast.receiver.values.flatMap(value => angularMessages(value, displayed));
  if (ast instanceof KeyedRead && ast.receiver instanceof LiteralArray) return ast.receiver.expressions.flatMap(value => angularMessages(value, displayed));
  if (displayed && ast instanceof BindingPipe && ast.name !== 't') return angularMessages(ast.exp, true);
  return [];
}

export function auditTemplate(text, label, catalog, report) {
  const parsed = parseTemplate(text, label);
  if (parsed.errors?.length) {
    for (const error of parsed.errors) report(`${label}: template parse error: ${error.toString()}`);
    return;
  }
  const where = ast => location(label, text, ast.sourceSpan?.start?.offset ?? ast.sourceSpan?.start ?? 0);
  class Expressions extends RecursiveAstVisitor {
    visitPipe(ast, context) {
      if (ast.name === 't') for (const message of angularMessages(ast.exp)) missingKey(message.text, catalog, report, where(message.ast));
      return super.visitPipe(ast, context);
    }
    visitCall(ast, context) {
      if (angularTranslator(ast)) for (const message of angularMessages(ast.args[0])) missingKey(message.text, catalog, report, where(message.ast));
      return super.visitCall(ast, context);
    }
  }
  const expressions = new Expressions();
  const inspect = ast => ast?.visit(expressions);
  const inspectVisible = ast => {
    for (const message of angularMessages(ast, true)) visibleText(message.text, report, where(message.ast));
  };
  class Template extends TmplAstRecursiveVisitor {
    visitElement(node) { if (!['style', 'script'].includes(node.name)) super.visitElement(node); }
    visitTemplate(node) { super.visitTemplate(node); for (const attribute of node.templateAttrs) attribute.visit(this); }
    visitText(node) { visibleText(node.value, report, where(node)); }
    visitBoundText(node) {
      inspect(node.value);
      for (const part of node.value.ast.strings ?? []) visibleText(part, report, where(node));
      for (const expression of node.value.ast.expressions ?? []) inspectVisible(expression);
    }
    visitTextAttribute(node) { if (attributes.has(node.name)) visibleText(node.value, report, where(node)); }
    visitBoundAttribute(node) { inspect(node.value); if (attributes.has(node.name.replace(/^attr\./, ''))) inspectVisible(node.value); }
    visitBoundEvent(node) { inspect(node.handler); }
    visitIfBlockBranch(node) { inspect(node.expression); super.visitIfBlockBranch(node); }
    visitForLoopBlock(node) { inspect(node.expression); inspect(node.trackBy); super.visitForLoopBlock(node); }
    visitSwitchBlock(node) { inspect(node.expression); super.visitSwitchBlock(node); }
    visitSwitchBlockCase(node) { inspect(node.expression); super.visitSwitchBlockCase(node); }
    visitLetDeclaration(node) { inspect(node.value); }
  }
  const visitor = new Template();
  for (const node of parsed.nodes) node.visit(visitor);
}

function readCatalogs(report) {
  const catalog = new Map();
  const directory = path.join(frontend, 'src/app/core/i18n');
  const registryFile = path.join(directory, 'translations.ts');
  const registry = ts.createSourceFile(registryFile, fs.readFileSync(registryFile, 'utf8'), ts.ScriptTarget.Latest, true);
  const registeredNames = new Set();
  const registeredFiles = new Set();
  function findRegistry(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(registry) === 'CATALOGS') {
      const array = unwrapTs(node.initializer);
      if (array && ts.isArrayLiteralExpression(array) && array.elements.every(ts.isIdentifier)) {
        for (const item of array.elements) registeredNames.add(item.text);
      } else report('src/app/core/i18n/translations.ts: CATALOGS must list static catalog identifiers');
    }
    ts.forEachChild(node, findRegistry);
  }
  findRegistry(registry);
  for (const statement of registry.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const bindings = statement.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings) && bindings.elements.some(item => registeredNames.has(item.name.text))) {
      registeredFiles.add(path.resolve(directory, statement.moduleSpecifier.text + '.ts'));
    }
  }
  if (!registeredFiles.size) report('No static German catalogs registered in CATALOGS.');
  const placeholders = value => [...new Set([...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]))].sort().join(',');
  for (const file of walkFiles(directory).filter(file => file.endsWith('.de.ts'))) {
    // An unregistered dictionary would otherwise hide a missing runtime
    // translation merely by existing on disk.
    if (!registeredFiles.has(file)) report(`${path.relative(frontend, file)}: German catalog is not registered in CATALOGS`);
    const text = fs.readFileSync(file, 'utf8');
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    function visit(node) {
      if (ts.isVariableDeclaration(node) && node.name.getText(source).endsWith('_DE')) {
        const object = unwrapTs(node.initializer);
        if (!object || !ts.isObjectLiteralExpression(object)) report(`${path.relative(frontend, file)}: translation catalog must be a static object`);
        else for (const property of object.properties) {
          const value = ts.isPropertyAssignment(property) ? unwrapTs(property.initializer) : null;
          const where = location(path.relative(frontend, file), text, property.getStart(source));
          if (!value || !ts.isStringLiteralLike(value) || ![ts.SyntaxKind.StringLiteral, ts.SyntaxKind.Identifier].includes(property.name.kind)) {
            report(`${where}: translation entries must have static string keys and values`); continue;
          }
          const key = property.name.text;
          if (placeholders(key) !== placeholders(value.text)) report(`${where}: interpolation placeholders differ for ${JSON.stringify(key)}`);
          catalog.set(key, value.text);
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  if (!catalog.size) report('No German translation catalog entries found.');
  return catalog;
}

function main() {
  const problems = new Set();
  const report = message => problems.add(message);
  const catalog = readCatalogs(report);
  const sources = walkFiles(path.join(frontend, 'src'));
  // index.html is the bootstrap document, not an Angular template. Its runtime
  // title and document language are assigned by I18nService and tested there.
  const templates = sources.filter(file => file.endsWith('.html') && path.relative(frontend, file) !== 'src/index.html')
    .map(file => ({text:fs.readFileSync(file, 'utf8'), label:path.relative(frontend, file)}));
  for (const file of sources.filter(file => file.endsWith('.ts') && !file.endsWith('.spec.ts') && !file.endsWith('.d.ts'))) {
    templates.push(...auditTypeScript(fs.readFileSync(file, 'utf8'), path.relative(frontend, file), catalog, report));
  }
  for (const template of templates) auditTemplate(template.text, template.label, catalog, report);
  if (problems.size) {
    for (const problem of problems) console.error(problem);
    console.error(`i18n check failed: ${problems.size} problem(s).`);
    process.exitCode = 1;
  } else console.log(`i18n check passed: ${templates.length} templates; ${catalog.size} German keys; visible text and interpolation placeholders checked.`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
