import dotenv from "dotenv";
dotenv.config();

import React, { useState, useRef } from "react";
import {
    render,
    Box,
    Text,
    useInput,
    useStdout
} from "ink";

import TextInput from "ink-text-input";
import { askStream } from "./llm.js";

const questions: string[] = [];
let inkInstance: ReturnType<typeof render> | null = null;

let exiting = false;

/**
 * =========================
 * EXIT CONTROL
 * =========================
 */
function exitCleanly() {
    if (exiting) return;
    exiting = true;

    if (inkInstance) {
        inkInstance.unmount();
        inkInstance = null;
    }

    setTimeout(() => {
        process.stdout.write("\x1b[2J\x1b[H");
        process.stdout.write("\x1b[?1049l");

        if (questions.length > 0) {
            process.stdout.write("\n─── Session History ─────────────────\n");
            questions.forEach((q, i) => {
                process.stdout.write(`  ${i + 1}. ${q}\n`);
            });
            process.stdout.write("─────────────────────────────────────\n");
        }

        process.exit(0);
    }, 20);
}

/**
 * =========================
 * APP
 * =========================
 */
function App() {
    const { stdout } = useStdout();
    const width = stdout.columns;
    const height = stdout.rows;

    const [value, setValue] = useState("");
    const [status, setStatus] = useState<"idle" | "thinking" | "error">("idle");

    const [messages, setMessages] = useState<
        { id: number; role: "user" | "assistant"; content: string }[]
    >([]);

    const [scrollOffset, setScrollOffset] = useState(0);
    const autoFollowRef = useRef(true);

    const idRef = useRef(0);
    const requestIdRef = useRef(0);
    const busyRef = useRef(false);

    /**
     * =========================
     * KEY HANDLING (ChatGPT style)
     * =========================
     */
    useInput((input, key) => {
        // Ctrl+C
        if (key.ctrl && input === "c") {
            exitCleanly();
        }

        // scroll up/down chat history
        if (key.upArrow) {
            autoFollowRef.current = false;
            setScrollOffset((p) => Math.min(p + 1, messages.length));
        }

        if (key.downArrow) {
            setScrollOffset((p) => Math.max(p - 1, 0));
        }

        if (key.pageUp) {
            autoFollowRef.current = false;
            setScrollOffset((p) => Math.min(p + 5, messages.length));
        }

        if (key.pageDown) {
            setScrollOffset((p) => Math.max(p - 5, 0));
        }

        // jump to bottom
        if (key.return) {
            autoFollowRef.current = true;
            setScrollOffset(0);
        }
    });

    /**
     * =========================
     * WINDOW (ChatGPT scrolling)
     * =========================
     */
    const headerHeight = 3;
    const inputHeight = 3;
    const maxMessages = Math.max(1, height - headerHeight - inputHeight);

    const visibleMessages = (() => {
        const start = Math.max(
            0,
            messages.length - maxMessages - scrollOffset
        );
        return messages.slice(start, start + maxMessages);
    })();

    return (
        <Box flexDirection="column" height={height} width={width}>
            {/* ================= HEADER ================= */}
            <Box
                borderStyle="double"
                paddingX={1}
                justifyContent="space-between"
            >
                <Text color="green">ChatGPT Terminal UI</Text>

                <Text>
                    {status === "thinking" && (
                        <Text color="yellow">● thinking</Text>
                    )}
                    {status === "idle" && <Text color="green">● idle</Text>}
                    {status === "error" && <Text color="red">● error</Text>}
                </Text>
            </Box>

            {/* ================= SIDEBAR + CHAT ================= */}
            <Box flexDirection="row" flexGrow={1}>
                {/* Sidebar */}
                <Box
                    width={20}
                    borderStyle="single"
                    flexDirection="column"
                    paddingX={1}
                >
                    <Text color="cyan">History</Text>
                    {questions.slice(-10).map((q, i) => (
                        <Text key={i} dimColor>
                            {i + 1}. {q.slice(0, 14)}
                        </Text>
                    ))}
                </Box>

                {/* Chat window */}
                <Box flexDirection="column" flexGrow={1} paddingX={1}>
                    {visibleMessages.map((msg) => (
                        <Box key={msg.id}>
                            <Text color={msg.role === "user" ? "blue" : "yellow"}>
                                {msg.role === "user" ? "You: " : "AI: "}
                            </Text>
                            <Text>{msg.content}</Text>
                        </Box>
                    ))}

                    {!autoFollowRef.current && (
                        <Text dimColor>
                            ↑ history mode (press ↓ / Enter to return bottom)
                        </Text>
                    )}
                </Box>
            </Box>

            {/* ================= INPUT ================= */}
            <Box borderStyle="single" paddingX={1}>
                <Text>{"> "}</Text>

                <TextInput
                    value={value}
                    onChange={setValue}
                    onSubmit={async (inputValue) => {
                        const trimmed = inputValue.trim();
                        if (!trimmed) return;

                        if (["/exit", "/quit", "/q"].includes(trimmed)) {
                            exitCleanly();
                            return;
                        }

                        if (busyRef.current) return;
                        busyRef.current = true;

                        setStatus("thinking");
                        questions.push(trimmed);

                        const userId = idRef.current++;
                        const aiId = idRef.current++;

                        setMessages((prev) => [
                            ...prev,
                            { id: userId, role: "user", content: trimmed },
                            { id: aiId, role: "assistant", content: "" }
                        ]);

                        setValue("");

                        const requestId = ++requestIdRef.current;
                        let buffer = "";

                        try {
                            await askStream(trimmed, (chunk) => {
                                if (requestId !== requestIdRef.current) return;

                                buffer += chunk;

                                if (buffer.length < 8) return;

                                const flush = buffer;
                                buffer = "";

                                setMessages((prev) =>
                                    prev.map((m) =>
                                        m.id === aiId
                                            ? { ...m, content: m.content + flush }
                                            : m
                                    )
                                );

                                if (autoFollowRef.current) {
                                    setScrollOffset(0);
                                }
                            });

                            if (buffer.length > 0) {
                                setMessages((prev) =>
                                    prev.map((m) =>
                                        m.id === aiId
                                            ? { ...m, content: m.content + buffer }
                                            : m
                                    )
                                );
                            }

                            setStatus("idle");
                        } catch (e) {
                            setStatus("error");
                        } finally {
                            busyRef.current = false;
                        }
                    }}
                />
            </Box>
        </Box>
    );
}

/**
 * =========================
 * BOOT
 * =========================
 */
process.stdout.write("\x1b[?1049h");

const instance = render(<App />, {
    exitOnCtrlC: false
});

inkInstance = instance;