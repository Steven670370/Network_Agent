import "dotenv/config";
import OpenAI from "openai";

const client = new OpenAI();
const model = process.env.LLM_MODEL || "gpt-4.1";

export async function askStream(
    prompt: string,
    onChunk?: (text: string) => void
): Promise<string> {
    const stream = await client.chat.completions.create({
        model,
        stream: true,
        messages: [
            {
                role: "user",
                content: prompt
            }
        ]
    });

    let fullText = "";

    for await (const chunk of stream) {
        const text = chunk.choices[0]?.delta?.content || "";
        if (!text) continue;

        fullText += text;
        onChunk?.(text);
    }

    return fullText;
}