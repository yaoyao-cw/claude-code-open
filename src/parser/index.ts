/**
 * 代码解析模块
 * 使用 Tree-sitter 进行代码分析（可选依赖）
 */

import * as fs from 'fs';
import * as path from 'path';

// 语法节点类型
export interface SyntaxNode {
  type: string;
  text: string;
  startPosition: { row: number; column: number };
  endPosition: { row: number; column: number };
  children: SyntaxNode[];
  parent?: SyntaxNode;
  isNamed: boolean;
}

// 代码符号类型
export type SymbolKind =
  | 'function'
  | 'class'
  | 'method'
  | 'property'
  | 'variable'
  | 'constant'
  | 'interface'
  | 'type'
  | 'enum'
  | 'module'
  | 'import'
  | 'export';

// 代码符号
export interface CodeSymbol {
  name: string;
  kind: SymbolKind;
  location: {
    file: string;
    startLine: number;
    startColumn: number;
    endLine: number;
    endColumn: number;
  };
  children?: CodeSymbol[];
  signature?: string;
  documentation?: string;
}

// 语言配置
export interface LanguageConfig {
  extensions: string[];
  symbolPatterns: {
    [key in SymbolKind]?: string[];
  };
}

// 支持的语言配置
const LANGUAGE_CONFIGS: Record<string, LanguageConfig> = {
  javascript: {
    extensions: ['.js', '.mjs', '.cjs'],
    symbolPatterns: {
      function: ['function_declaration', 'arrow_function'],
      class: ['class_declaration'],
      variable: ['variable_declarator'],
      import: ['import_statement'],
      export: ['export_statement'],
    },
  },
  typescript: {
    extensions: ['.ts', '.tsx', '.mts', '.cts'],
    symbolPatterns: {
      function: ['function_declaration', 'arrow_function'],
      class: ['class_declaration'],
      interface: ['interface_declaration'],
      type: ['type_alias_declaration'],
      enum: ['enum_declaration'],
      import: ['import_statement'],
      export: ['export_statement'],
    },
  },
  python: {
    extensions: ['.py', '.pyw'],
    symbolPatterns: {
      function: ['function_definition'],
      class: ['class_definition'],
      import: ['import_statement', 'import_from_statement'],
    },
  },
};

// 简化的代码解析器
export class SimpleCodeParser {
  parseFile(filePath: string): CodeSymbol[] {
    const content = fs.readFileSync(filePath, 'utf-8');
    const ext = path.extname(filePath);
    const language = this.detectLanguage(ext);
    if (!language) return [];
    return this.parseContent(content, filePath, language);
  }

  private detectLanguage(ext: string): string | null {
    for (const [lang, config] of Object.entries(LANGUAGE_CONFIGS)) {
      if (config.extensions.includes(ext)) return lang;
    }
    return null;
  }

  parseContent(content: string, filePath: string, language: string): CodeSymbol[] {
    const symbols: CodeSymbol[] = [];
    const lines = content.split('\n');

    const patterns: Record<string, RegExp> = {
      function: /^(?:export\s+)?(?:async\s+)?function\s+(\w+)/,
      class: /^(?:export\s+)?class\s+(\w+)/,
      interface: /^(?:export\s+)?interface\s+(\w+)/,
      type: /^(?:export\s+)?type\s+(\w+)/,
      enum: /^(?:export\s+)?enum\s+(\w+)/,
      variable: /^(?:export\s+)?(?:const|let|var)\s+(\w+)/,
    };

    lines.forEach((line, idx) => {
      const trimmed = line.trim();
      for (const [kind, pattern] of Object.entries(patterns)) {
        const match = trimmed.match(pattern);
        if (match) {
          symbols.push({
            name: match[1],
            kind: kind as SymbolKind,
            location: {
              file: filePath,
              startLine: idx + 1,
              startColumn: line.indexOf(match[1]),
              endLine: idx + 1,
              endColumn: line.indexOf(match[1]) + match[1].length,
            },
            signature: trimmed.slice(0, 80),
          });
          break;
        }
      }
    });

    return symbols;
  }
}

// 代码分析器
export class CodeAnalyzer {
  private parser: SimpleCodeParser;

  constructor() {
    this.parser = new SimpleCodeParser();
  }

  analyzeFile(filePath: string): CodeSymbol[] {
    return this.parser.parseFile(filePath);
  }

  analyzeDirectory(dirPath: string, extensions?: string[]): CodeSymbol[] {
    const symbols: CodeSymbol[] = [];
    const allExtensions = extensions || ['.ts', '.js', '.py'];

    const walkDir = (dir: string) => {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          if (!['node_modules', '.git', 'dist'].includes(entry.name)) {
            walkDir(fullPath);
          }
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name);
          if (allExtensions.includes(ext)) {
            symbols.push(...this.analyzeFile(fullPath));
          }
        }
      }
    };

    walkDir(dirPath);
    return symbols;
  }

  findSymbol(name: string, symbols: CodeSymbol[]): CodeSymbol[] {
    return symbols.filter(s => s.name.toLowerCase().includes(name.toLowerCase()));
  }

  getOutline(filePath: string): CodeSymbol[] {
    return this.analyzeFile(filePath);
  }
}

// 默认实例
export const codeParser = new SimpleCodeParser();
export const codeAnalyzer = new CodeAnalyzer();
