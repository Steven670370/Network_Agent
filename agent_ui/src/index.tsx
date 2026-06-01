import dotenv from "dotenv";
    dotenv.config();
import React, { useState, useRef } from "react";
import { render, Box, Text, useApp } from "ink";
import TextInput from "ink-text-input";
import { askStream } from "./llm.js";
import useStdoutDimensions from "ink-use-stdout-dimensions";

const questions: string[] = [];
let inkInstance: ReturnType<typeof render> | null = null;

function handleExit(exit?: () => void) {
    if (inkInstance) {
        inkInstance.unmount();
    }

    if (questions.length > 0) {
        process.stdout.write("\n─── Network Agent ──────────────────\n");
        questions.forEach((q, i) => {
            process.stdout.write(`  Q${i + 1}: ${q}\n`);
        });
        process.stdout.write("────────────────────────────────────\n");
    }

    exit?.();
    process.exit(0);
}

function App() {
    const { exit } = useApp();

    const [value, setValue] = useState("");
    const [status, setStatus] = useState<"idle" | "thinking" | "error">("idle");
    const [messages, setMessages] = useState<
        { id: number; role: string; content: string }[]
    >([]);

    const [width, height] = useStdoutDimensions();

    const idRef = useRef(0);

    const requestIdRef = useRef(0);

    return (
        <Box flexDirection="column" height={height} width={width}>
            <Box
                borderStyle="double"
                flexDirection="row"
                justifyContent="space-between"
                padding={1}
            >
                <Text color="green">Network Agent</Text>
                <Text>
                    {status === "thinking" && <Text color="yellow">Thinking...</Text>}
                    {status === "error" && <Text color="red">Error occurred</Text>}
                    {status === "idle" && <Text color="green">Idle</Text>}
                </Text>
            </Box>

            <Box flexDirection="column" flexGrow={1} overflowY="hidden">
                {messages.map((msg) => (
                    <Box key={msg.id}>
                        <Text color={msg.role === "user" ? "blue" : "yellow"}>
                            {msg.role === "user" ? "User" : "Agent"}:
                        </Text>{" "}
                        <Text>{msg.content}</Text>
                    </Box>
                ))}
            </Box>

            <Box borderStyle="single" padding={1}>
                <Text>{"> "}</Text>

                <TextInput
                    value={value}
                    onChange={setValue}
                    onSubmit={async (inputValue) => {
                        const trimmed = inputValue.trim();
                        if (!trimmed) return;

                        // Ctrl commands
                        if (["/exit", "/quit", "/q"].includes(trimmed)) {
                            handleExit(exit);
                            return;
                        }

                        setStatus("thinking");

                        questions.push(trimmed);

                        const userMsgId = idRef.current++;
                        const assistantMsgId = idRef.current++;

                        setMessages((prev) => [
                            ...prev,
                            { id: userMsgId, role: "user", content: trimmed },
                            { id: assistantMsgId, role: "assistant", content: "" }
                        ]);

                        setValue("");

                        // ✅ 竞态控制
                        const currentRequestId = ++requestIdRef.current;

                        // ✅ chunk buffer（解决 UI 抖动）
                        let buffer = "";
                        let accumulated = "";

                        try {
                            await askStream(trimmed, (chunk) => {
                                // ❗ 丢弃旧请求
                                if (currentRequestId !== requestIdRef.current) return;

                                buffer += chunk;
                                accumulated += chunk;

                                // throttle：避免每个 token 都 setState
                                if (buffer.length < 8) return;
                                const flush = buffer;
                                buffer = "";

                                setMessages((prev) =>
                                    prev.map((msg) =>
                                        msg.id === assistantMsgId
                                            ? { ...msg, content: msg.content + flush }
                                            : msg
                                    )
                                );
                            });

                            // flush 剩余 buffer
                            if (buffer.length > 0) {
                                const flush = buffer;
                                setMessages((prev) =>
                                    prev.map((msg) =>
                                        msg.id === assistantMsgId
                                            ? { ...msg, content: msg.content + flush }
                                            : msg
                                    )
                                );
                            }

                            setStatus("idle");
                        } catch (error) {
                            setStatus("error");

                            setMessages((prev) =>
                                prev.map((msg) =>
                                    msg.id === assistantMsgId
                                        ? { ...msg, content: "[Error: Failed to get response]" }
                                        : msg
                                )
                            );
                        }
                    }}
                    placeholder="Enter your message..."
                />
            </Box>
        </Box>
    );
}

const instance = render(<App />, {
    alternateScreen: true,
    exitOnCtrlC: false
});

inkInstance = instance;

process.stdin.setRawMode?.(true);
process.stdin.resume();

process.stdin.on("data", (data) => {
    if (data.toString() === "\x03") {
        handleExit(() => inkInstance?.unmount());
    }
});