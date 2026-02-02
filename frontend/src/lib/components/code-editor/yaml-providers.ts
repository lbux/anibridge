/* eslint-disable @typescript-eslint/no-explicit-any */
import type * as Monaco from "monaco-editor/esm/vs/editor/editor.api.js";

class YamlSchemaManager {
    private schema: any = { properties: {}, definitions: {} };
    private suggestionsMap: Map<string, any[]> = new Map();
    private schemaUrl?: string;
    private rawSchema: any | null = null;
    public ready: Promise<void>;

    constructor() {
        this.parseSchema();
        this.ready = Promise.resolve();
    }

    setSchemaUrl(url: string | undefined) {
        if (!url) {
            this.schemaUrl = undefined;
            this.rawSchema = null;
            this.schema = { properties: {}, definitions: {} };
            this.suggestionsMap.clear();
            this.parseSchema();
            this.ready = Promise.resolve();
            return;
        }

        if (url === this.schemaUrl) return;
        this.schemaUrl = url;
        this.rawSchema = null;
        this.ready = this.fetchLatestSchema();
    }

    setSchemaObject(schema: any) {
        if (!schema) return;
        this.rawSchema = schema;
        this.schema = schema;
        this.suggestionsMap.clear();
        this.parseSchema();
    }

    private getDefinitions() {
        return this.schema.definitions || this.schema.$defs || {};
    }

    private resolveRef(ref: string) {
        if (!ref || !ref.startsWith("#")) return null;
        const pointer = ref.replace(/^#\/?/, "");
        if (!pointer) return this.schema;
        const segments = pointer
            .split("/")
            .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
        let current: any = this.schema;
        for (const seg of segments) {
            if (current && typeof current === "object" && seg in current) {
                current = current[seg];
            } else {
                return null;
            }
        }
        return current;
    }

    private mergeSchemas(schemas: any[]) {
        const result: any = {
            type: "object",
            properties: {},
            required: [] as string[],
        };
        for (const schema of schemas) {
            if (!schema || typeof schema !== "object") continue;
            if (schema.description && !result.description)
                result.description = schema.description;
            if (schema.title && !result.title) result.title = schema.title;
            if (schema.type && !result.type) result.type = schema.type;
            if (schema.properties) {
                result.properties = { ...result.properties, ...schema.properties };
            }
            if (Array.isArray(schema.required)) {
                result.required = Array.from(
                    new Set([...(result.required || []), ...schema.required]),
                );
            }
            if (
                schema.additionalProperties !== undefined &&
                result.additionalProperties === undefined
            ) {
                result.additionalProperties = schema.additionalProperties;
            }
            if (schema.items && !result.items) result.items = schema.items;
        }
        return result;
    }

    private resolveSchema(schema: any, visited = new Set<any>()): any {
        if (!schema || typeof schema !== "object") return schema;
        if (visited.has(schema)) return schema;
        visited.add(schema);

        if (schema.$ref) {
            const resolved = this.resolveRef(schema.$ref);
            if (resolved) {
                const merged = { ...resolved, ...schema };
                delete merged.$ref;
                return this.resolveSchema(merged, visited);
            }
        }

        if (Array.isArray(schema.allOf) && schema.allOf.length > 0) {
            const merged = this.mergeSchemas(
                schema.allOf.map((s: any) => this.resolveSchema(s, visited)),
            );
            return this.resolveSchema(
                { ...merged, ...schema, allOf: undefined },
                visited,
            );
        }

        return schema;
    }

    private collectProperties(schema: any) {
        const resolved = this.resolveSchema(schema);
        const properties: Record<string, any> = {};

        if (resolved?.properties) {
            Object.assign(properties, resolved.properties);
        }

        const variants = [...(resolved?.oneOf || []), ...(resolved?.anyOf || [])];
        for (const variant of variants) {
            const props = this.collectProperties(variant);
            Object.assign(properties, props);
        }

        return properties;
    }

    private async fetchLatestSchema(retries = 2): Promise<void> {
        if (!this.schemaUrl) return;
        if (this.rawSchema) return;
        try {
            const response = await fetch(this.schemaUrl);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            this.schema = await response.json();
            this.suggestionsMap.clear();
            this.parseSchema();
        } catch (e) {
            if (retries > 0) {
                await new Promise((r) => setTimeout(r, 1000));
                return this.fetchLatestSchema(retries - 1);
            }
            console.error("Failed to fetch schema after retries", e);
        }
    }

    private parseSchema() {
        const definitions = this.getDefinitions();
        const rootSuggestions: any[] = [];
        const rootProps = this.collectProperties(this.schema);
        if (rootProps && Object.keys(rootProps).length > 0) {
            for (const [key, value] of Object.entries(rootProps)) {
                const val = value as any;
                rootSuggestions.push({
                    label: key,
                    kind: 1,
                    documentation: this.getDescription(val),
                    insertText: this.generateInsertText(key, val),
                });
            }
        }
        this.suggestionsMap.set("root", rootSuggestions);

        if (Object.keys(definitions).length > 0) {
            for (const [defName, defValue] of Object.entries(definitions)) {
                const def = defValue as any;
                const defProps = this.collectProperties(def);
                if (defProps && Object.keys(defProps).length > 0) {
                    const suggestions: any[] = [];
                    for (const [key, value] of Object.entries(defProps)) {
                        const val = value as any;
                        suggestions.push({
                            label: key,
                            kind: 1,
                            documentation: this.getDescription(val),
                            insertText: this.generateInsertText(key, val),
                        });
                    }
                    this.suggestionsMap.set(defName, suggestions);
                }
            }
        }
    }

    private getDescription(val: any, visited = new Set<string>()): string {
        if (!val) return "";
        if (val.description) return val.description;

        if (val.$ref) {
            if (visited.has(val.$ref)) return "";
            visited.add(val.$ref);
            const defName = val.$ref.includes("/")
                ? val.$ref.split("/").pop()
                : val.$ref.replace("#", "");
            const def = (this.schema.definitions || this.schema.$defs)?.[defName];
            if (def && def.description) return def.description;
            if (def) return this.getDescription(def, visited);
        }

        const nested = val.oneOf || val.anyOf || [];
        for (const sub of nested) {
            const desc = this.getDescription(sub, visited);
            if (desc) return desc;
        }

        return "";
    }

    private generateInsertText(key: string, val: any): string {
        const type = Array.isArray(val.type) ? val.type[0] : val.type;

        if (type === "array") {
            return `${key}:\n  - \${1}`;
        }
        if (type === "object" || val.$ref || val.properties || val.oneOf || val.anyOf) {
            return `${key}:\n  \${1}`;
        }
        return `${key}: `;
    }

    private getSchemaForPath(path: string[]) {
        let current: any = this.resolveSchema(this.schema);
        for (const segment of path) {
            if (!current) return null;
            current = this.resolveSchema(current);

            if (segment === "[]") {
                const items = current.items || current.prefixItems?.[0];
                current = this.resolveSchema(items);
                continue;
            }

            const directProp = current.properties?.[segment];
            if (directProp) {
                current = directProp;
                continue;
            }

            const variants = [
                ...(current.oneOf || []),
                ...(current.anyOf || []),
                ...(current.allOf || []),
            ];
            let found: any = null;
            for (const variant of variants) {
                const v = this.resolveSchema(variant);
                if (v?.properties?.[segment]) {
                    found = v.properties[segment];
                    break;
                }
            }

            if (found) {
                current = found;
                continue;
            }

            if (
                current.additionalProperties &&
                typeof current.additionalProperties === "object"
            ) {
                current = current.additionalProperties;
                continue;
            }

            return null;
        }

        return this.resolveSchema(current);
    }

    getSuggestionsForPath(path: string[]) {
        if (path.length === 0) return this.suggestionsMap.get("root") || [];

        const schema = this.getSchemaForPath(path);
        if (!schema) return [];

        const props = this.collectProperties(schema);
        return Object.entries(props).map(([key, value]) => ({
            label: key,
            kind: 1,
            documentation: this.getDescription(value),
            insertText: this.generateInsertText(key, value),
        }));
    }

    getDocumentation(word: string): string | null {
        if (this.schema.properties?.[word]) {
            return `**${word}**\n\n${this.getDescription(this.schema.properties[word])}`;
        }

        const definitions = this.schema.definitions || this.schema.$defs;
        if (definitions?.[word]) {
            return `**${word}**\n\n${definitions[word].description || ""}`;
        }

        if (definitions) {
            for (const [defName, def] of Object.entries(definitions) as any[]) {
                if (def.properties?.[word]) {
                    return `**${word}** (in ${defName})\n\n${this.getDescription(
                        def.properties[word],
                    )}`;
                }

                const nested = [
                    ...(def.oneOf || []),
                    ...(def.anyOf || []),
                    ...(def.allOf || []),
                ];
                for (const sub of nested) {
                    if (sub.properties?.[word]) {
                        return `**${word}** (in ${defName})\n\n${this.getDescription(
                            sub.properties[word],
                        )}`;
                    }
                }
            }
        }
        return null;
    }

    getDocumentationAtPath(path: string[], word: string): string | null {
        const schema = this.getSchemaForPath(path);
        const resolved = schema ? this.resolveSchema(schema) : null;
        const props = resolved ? this.collectProperties(resolved) : null;
        const propSchema = props?.[word];
        if (propSchema) {
            return `**${word}**\n\n${this.getDescription(propSchema)}`;
        }
        return this.getDocumentation(word);
    }
}

const yamlSchemaManager = new YamlSchemaManager();

function getPath(model: Monaco.editor.ITextModel, position: Monaco.Position): string[] {
    const lineContent = model.getLineContent(position.lineNumber);
    const indent = lineContent.match(/^\s*/)?.[0].length || 0;
    if (indent === 0) return [];

    let currentIndent = indent;
    const tokens: string[] = [];

    for (let i = position.lineNumber - 1; i >= 1; i--) {
        const line = model.getLineContent(i);
        const lineIndent = line.match(/^\s*/)?.[0].length || 0;
        if (lineIndent < currentIndent) {
            const listItem = line.match(/^\s*-\s+/);
            if (listItem) {
                tokens.push("[]");
                currentIndent = lineIndent;
                continue;
            }

            const match = line.match(/^\s*([\w-]+):/);
            if (match) {
                tokens.push(match[1]);
                currentIndent = lineIndent;
            }
        }
    }

    return tokens.reverse();
}

export function registerYamlCompletionProvider(monaco: typeof Monaco) {
    return monaco.languages.registerCompletionItemProvider("yaml", {
        triggerCharacters: [" ", ":", "-", "."],
        provideCompletionItems: (model, position) => {
            const lineContent = model.getLineContent(position.lineNumber);
            const textBeforeCursor = lineContent.substring(0, position.column - 1);

            if (textBeforeCursor.endsWith(":")) {
                return { suggestions: [] };
            }

            if (/: /.test(textBeforeCursor)) {
                return { suggestions: [] };
            }

            const word = model.getWordUntilPosition(position);
            const range = {
                startLineNumber: position.lineNumber,
                endLineNumber: position.lineNumber,
                startColumn: word.startColumn,
                endColumn: word.endColumn,
            };

            const path = getPath(model, position);
            const suggestions = yamlSchemaManager
                .getSuggestionsForPath(path)
                .map((s) => ({
                    ...s,
                    range,
                    kind: monaco.languages.CompletionItemKind.Property,
                    insertTextRules: s.insertText.includes("$")
                        ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet
                        : undefined,
                }));

            return { suggestions };
        },
    });
}

export function registerYamlHoverProvider(monaco: typeof Monaco) {
    return monaco.languages.registerHoverProvider("yaml", {
        provideHover: (model, position) => {
            const word = model.getWordAtPosition(position);
            if (!word) return null;

            const path = getPath(model, position);
            const documentation = yamlSchemaManager.getDocumentationAtPath(
                path,
                word.word,
            );
            if (documentation) {
                return {
                    range: new monaco.Range(
                        position.lineNumber,
                        word.startColumn,
                        position.lineNumber,
                        word.endColumn,
                    ),
                    contents: [{ value: documentation }],
                };
            }

            return null;
        },
    });
}

export function registerYamlProviders(monaco: typeof Monaco) {
    return [registerYamlCompletionProvider(monaco), registerYamlHoverProvider(monaco)];
}

export function setYamlSchemaUrl(url: string | undefined) {
    yamlSchemaManager.setSchemaUrl(url);
}

export function setYamlSchemaObject(schema: unknown) {
    if (!schema) return;
    yamlSchemaManager.setSchemaObject(schema);
}
