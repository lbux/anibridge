<script lang="ts">
    import { onDestroy, onMount } from "svelte";

    import Ajv, { type ErrorObject } from "ajv";
    import jsyaml from "js-yaml";
    import type * as Monaco from "monaco-editor";

    type Props = {
        value?: string;
        readOnly?: boolean;
        fontSize?: string;
        fileUri?: string;
        autoHeight?: boolean;
        schemaObject?: unknown;
        schemaUrl?: string;
        theme?: "light" | "dark";
    };

    let {
        value = $bindable(""),
        readOnly = false,
        fontSize = "13px",
        fileUri = undefined,
        autoHeight = false,
        schemaObject = undefined,
        schemaUrl = undefined,
        theme = "dark",
    }: Props = $props();

    let monacoModule: typeof import("./monaco") | null = null;
    let monacoInstance = $state<typeof import("monaco-editor") | null>(null);
    let editorElement: HTMLDivElement;
    let editor = $state<Monaco.editor.IStandaloneCodeEditor | null>(null);
    let model = $state<Monaco.editor.ITextModel | null>(null);
    let ownsModel = false;
    let resizeObserver = $state<ResizeObserver | null>(null);
    let changeDisposable = $state<Monaco.IDisposable | null>(null);
    let autoHeightDispose = $state<(() => void) | null>(null);
    let cursorDisposable = $state<Monaco.IDisposable | null>(null);
    let validationMarkers = $state<Monaco.editor.IMarkerData[]>([]);
    let schemaForValidation = $state<unknown | null>(null);
    let schemaFetchAbort: AbortController | null = null;
    let activeLine = $state<number | null>(null);

    const langId = "yaml";
    const editorTheme = $derived(
        theme === "dark" ? "catppuccin-mocha" : "catppuccin-latte",
    );
    const fontSizeValue = $derived(parseInt(fontSize.replace("px", ""), 10));
    const markers = $derived.by(() => {
        const monaco = monacoInstance;
        if (!model || !monaco) return [];

        const syntaxMarkers: Monaco.editor.IMarkerData[] = [];
        try {
            jsyaml.load(value);
        } catch (e: unknown) {
            const err = e as {
                mark?: { line: number; column: number };
                reason?: string;
                message?: string;
            };
            const mark = err.mark;

            if (mark) {
                const lineCount = model.getLineCount();
                const lineNumber = Math.min(Math.max(1, mark.line + 1), lineCount);
                const maxColumn = model.getLineMaxColumn(lineNumber);

                syntaxMarkers.push({
                    severity: monaco.MarkerSeverity.Error,
                    message: err.reason || err.message || "YAML error",
                    startLineNumber: lineNumber,
                    startColumn: Math.min(mark.column + 1, maxColumn),
                    endLineNumber: lineNumber,
                    endColumn: maxColumn,
                });
            } else {
                syntaxMarkers.push({
                    severity: monaco.MarkerSeverity.Error,
                    message: err.message || "YAML error",
                    startLineNumber: 1,
                    startColumn: 1,
                    endLineNumber: 1,
                    endColumn: 1,
                });
            }
        }

        return [...syntaxMarkers, ...validationMarkers];
    });

    function escapeRegExp(value: string) {
        return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    function findLineForKey(key: string) {
        if (!model) return 1;
        const lineCount = model.getLineCount();
        const pattern = new RegExp(`^\\s*${escapeRegExp(key)}\\s*:`);
        for (let i = 1; i <= lineCount; i++) {
            const line = model.getLineContent(i);
            if (pattern.test(line)) return i;
        }
        return 1;
    }

    function decodePointerSegment(segment: string) {
        return segment.replace(/~1/g, "/").replace(/~0/g, "~");
    }

    function updateHeight() {
        if (!editor || !editorElement || !autoHeight) return;
        const contentHeight = editor.getContentHeight();
        editorElement.style.height = `${contentHeight}px`;
        editor.layout();
    }

    onMount(async () => {
        if (!editorElement) return;

        monacoModule = await import("./monaco");
        const monaco = monacoModule.monaco;
        monacoInstance = monaco;

        await monacoModule.initShiki(monaco);
        if (schemaObject) {
            monacoModule.setYamlSchemaObject(schemaObject);
        } else if (schemaUrl) {
            monacoModule.setYamlSchemaUrl(schemaUrl);
        }
        await new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
        );

        const uri = fileUri
            ? monaco.Uri.parse(fileUri)
            : monaco.Uri.parse(`inmemory://model-${Date.now()}.${langId}`);
        const existingModel = monaco.editor.getModel(uri);
        ownsModel = !existingModel;
        model = existingModel || monaco.editor.createModel(value, langId, uri);
        const activeModel = model;

        const createdEditor = monaco.editor.create(editorElement, {
            model: activeModel,
            automaticLayout: false,
            theme: editorTheme,
            readOnly,
            fontSize: fontSizeValue,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on",
            fixedOverflowWidgets: true,
            dragAndDrop: false,
            contextmenu: true,
            quickSuggestions: { other: true, comments: false, strings: true },
            suggestOnTriggerCharacters: true,
            fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", "Courier New", monospace',
            fontLigatures: false,
            padding: { top: 10, bottom: 10 },
            scrollbar: autoHeight
                ? { vertical: "hidden", handleMouseWheel: false }
                : { vertical: "auto", handleMouseWheel: true },
        });

        editor = createdEditor;

        createdEditor.addAction({
            id: "mre.selectAll",
            label: "Select All",
            contextMenuGroupId: "9_cutcopypaste",
            contextMenuOrder: 4,
            run: (ed: Monaco.editor.IStandaloneCodeEditor) => {
                ed.focus();
                const activeModel = ed.getModel();
                if (activeModel) {
                    ed.setSelection(activeModel.getFullModelRange());
                }
            },
        });

        if (activeModel) {
            changeDisposable = activeModel.onDidChangeContent(() => {
                value = activeModel.getValue() || "";
            });
        }

        cursorDisposable = createdEditor.onDidChangeCursorPosition(
            (e: Monaco.editor.ICursorPositionChangedEvent) => {
                activeLine = e.position.lineNumber;
            },
        );

        resizeObserver = new ResizeObserver(() => {
            requestAnimationFrame(() => {
                editor?.layout();
            });
        });
        resizeObserver.observe(editorElement);
    });

    onDestroy(() => {
        changeDisposable?.dispose();
        cursorDisposable?.dispose();
        resizeObserver?.disconnect();
        autoHeightDispose?.();
        editor?.dispose();
        if (ownsModel) model?.dispose();
    });

    $effect(() => {
        if (monacoModule) {
            if (schemaObject) {
                monacoModule.setYamlSchemaObject(schemaObject);
            } else if (schemaUrl) {
                monacoModule.setYamlSchemaUrl(schemaUrl);
            }
        }
    });

    $effect(() => {
        if (schemaFetchAbort) {
            schemaFetchAbort.abort();
            schemaFetchAbort = null;
        }

        if (schemaObject) {
            schemaForValidation = schemaObject;
            return;
        }

        if (!schemaUrl) {
            schemaForValidation = null;
            return;
        }

        const controller = new AbortController();
        schemaFetchAbort = controller;
        (async () => {
            try {
                const response = await fetch(schemaUrl, { signal: controller.signal });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const json = await response.json();
                if (!controller.signal.aborted) {
                    schemaForValidation = json;
                }
            } catch {
                if (!controller.signal.aborted) {
                    schemaForValidation = null;
                }
            }
        })();

        return () => {
            controller.abort();
        };
    });

    $effect(() => {
        const activeModel = model;
        const monaco = monacoInstance;
        if (!activeModel || !monaco || !schemaForValidation) {
            validationMarkers = [];
            return;
        }

        let data: unknown;
        try {
            data = jsyaml.load(value);
        } catch {
            validationMarkers = [];
            return;
        }

        const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false });
        let validate;
        try {
            validate = ajv.compile(schemaForValidation as Record<string, unknown>);
        } catch {
            validationMarkers = [];
            return;
        }

        const valid = validate(data);
        if (valid) {
            validationMarkers = [];
            return;
        }

        const errors = validate.errors || [];
        validationMarkers = errors
            .map((err: ErrorObject) => {
                const pointer = err.instancePath || "";
                const segments = pointer
                    .split("/")
                    .filter(Boolean)
                    .map((s: string) => decodePointerSegment(s));
                let key = segments.length > 0 ? segments[segments.length - 1] : "";
                if (err.keyword === "required" && typeof err.params === "object") {
                    const missing = (err.params as { missingProperty?: string })
                        .missingProperty;
                    if (missing) key = missing;
                }
                if (/^\d+$/.test(key) && segments.length > 1) {
                    key = segments[segments.length - 2];
                }

                const lineNumber = key ? findLineForKey(key) : 1;
                if (activeLine !== null && lineNumber === activeLine) {
                    return null;
                }
                const maxColumn = activeModel.getLineMaxColumn(lineNumber);
                return {
                    severity: monaco.MarkerSeverity.Error,
                    message: err.message || "Schema validation error",
                    startLineNumber: lineNumber,
                    startColumn: 1,
                    endLineNumber: lineNumber,
                    endColumn: maxColumn,
                };
            })
            .filter((marker): marker is Monaco.editor.IMarkerData => Boolean(marker));
    });

    $effect(() => {
        if (model && value !== model.getValue()) {
            model.setValue(value);
        }
    });

    $effect(() => {
        if (model && monacoInstance) {
            monacoInstance.editor.setModelLanguage(model, langId);
        }
    });

    $effect(() => {
        if (model && monacoInstance) {
            monacoInstance.editor.setModelMarkers(model, "yaml-linter", markers);
        }
    });

    $effect(() => {
        if (editor) {
            editor.updateOptions({
                readOnly,
                fontSize: fontSizeValue,
                wordWrap: "on",
                fixedOverflowWidgets: true,
                dragAndDrop: false,
                scrollbar: autoHeight
                    ? { vertical: "hidden", handleMouseWheel: false }
                    : { vertical: "auto", handleMouseWheel: true },
            });
            editor.layout();
        }
    });

    $effect(() => {
        if (editor && monacoInstance) {
            monacoInstance.editor.setTheme(editorTheme);
        }
    });

    $effect(() => {
        if (autoHeightDispose) {
            autoHeightDispose();
            autoHeightDispose = null;
        }

        if (editor && autoHeight) {
            const disposable = editor.onDidContentSizeChange(updateHeight);
            updateHeight();
            autoHeightDispose = () => disposable.dispose();
        } else if (editorElement) {
            editorElement.style.height = "";
        }
    });
</script>

<div
    class={`editor-root ${autoHeight ? "auto" : ""}`}
    bind:this={editorElement}>
</div>

<style>
    .editor-root {
        width: 100%;
        height: 100%;
        min-height: 0;
        background: transparent;
    }

    .editor-root.auto {
        height: auto;
    }

    .editor-root :global(.monaco-editor) {
        background: transparent;
    }

    .editor-root :global(.monaco-editor-background) {
        background: transparent;
    }

    .editor-root :global(.monaco-editor .margin) {
        background: transparent;
    }
</style>
