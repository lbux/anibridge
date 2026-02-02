import * as monaco from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js";
import "monaco-editor/esm/vs/editor/editor.all.js";

import { shikiToMonaco } from "@shikijs/monaco";
import { createHighlighter } from "shiki";

import {
    registerYamlProviders,
    setYamlSchemaObject,
    setYamlSchemaUrl,
} from "./yaml-providers";

self.MonacoEnvironment = { getWorker: () => new editorWorker() };

let shikiPromise: Promise<void> | null = null;

export async function initShiki(monacoInstance: typeof monaco) {
    if (shikiPromise) return shikiPromise;

    shikiPromise = (async () => {
        const highlighter = await createHighlighter({
            themes: ["catppuccin-mocha", "catppuccin-latte"],
            langs: ["yaml"],
        });

        const registeredLanguages = monacoInstance.languages
            .getLanguages()
            .map((lang) => lang.id);
        const langsToRegister = ["yaml"];

        for (const lang of langsToRegister) {
            if (!registeredLanguages.includes(lang)) {
                monacoInstance.languages.register({ id: lang });
            }
        }

        shikiToMonaco(highlighter, monacoInstance);
        registerProviders();
    })();

    return shikiPromise;
}

let yamlProviders: monaco.IDisposable[] = [];

export function registerProviders() {
    yamlProviders.forEach((p) => p.dispose());
    yamlProviders = registerYamlProviders(monaco);
}

export { setYamlSchemaObject, setYamlSchemaUrl };

if (typeof window !== "undefined") {
    (window as unknown as { monaco: typeof monaco }).monaco = monaco;
}

export { monaco };
export type Monaco = typeof monaco;
