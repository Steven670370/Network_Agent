import "dotenv/config";
import React, { useState, useRef } from "react";
import {render, Box, Text} from "ink";
import TextInput from "ink-text-input";
import {askStream} from "./llm.js";
import useStdoutDimensions from "ink-use-stdout-dimensions";

const questions: string[] = [];
let inkInstance: ReturnType<typeof render> | null = null;

function handleExit() {
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

    process.exit(0);
}

function App() {
    const [value, setValue] = useState("");
    const [status, setStatus] = useState<"idle" | "thinking"|"error">("idle");
    const [messages, setMessages] = useState<{id: number; role: string; content: string}[]>([]);
    const [width, height] = useStdoutDimensions();
    const idRef = useRef(0);

    return (
        <Box flexDirection="column" height = {height} width = {width}>
            <Box borderStyle="double" flexDirection="row" justifyContent="space-between" padding={1}>
                <Text color="green">Network Agent</Text>
                <Text>
                    {status == "thinking" && <Text color="yellow">Thinking...</Text>}
                    {status == "error" && <Text color="red">Error occurred</Text>}
                    {status == "idle" && <Text color="green">Idle</Text>}
                </Text>
            </Box>

            <Box flexDirection="column" flexGrow={1} overflowY="hidden">
                {messages.map((msg) => (
                    <Box key={msg.id}>
                        <Text color={msg.role === "user" ? "blue" : "yellow"}>
                            {msg.role === "user" ? "User" : "Agent"}: 
                        </Text>
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
                        if (["/exit", "/quit", "/q"].includes(trimmed)) {
                            handleExit();
                            return;
                        }

                        setStatus("thinking");

                        questions.push(inputValue);

                        const userMsg = { id: idRef.current++, role: "user", content: inputValue };
                        const assistantMsg = { id: idRef.current++, role: "assistant", content: "" };
                        setMessages((prev) => [...prev, userMsg, assistantMsg]);
                        setValue("");

                        try {
                            await askStream(inputValue, (chunk) => {
                                setMessages((prev) =>
                                    prev.map((msg) =>
                                        msg.id === assistantMsg.id
                                            ? { ...msg, content: msg.content + chunk }
                                            : msg
                                    )
                                );
                            });

                            setStatus("idle");

                        } catch (error) {
                            setStatus("error");

                            setMessages((prev) =>
                                prev.map((msg) =>
                                    msg.id === assistantMsg.id
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
    exitOnCtrlC: false,
});

inkInstance = instance;

process.stdin.on("data", function onCtrlC(data) {
    const input = data.toString().toLowerCase();

    if (input !== "\x03" ) return;
    process.stdin.off("data", onCtrlC);

    handleExit();
});
