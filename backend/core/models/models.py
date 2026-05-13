import os
import dotenv
from openai import AsyncOpenAI

dotenv.load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

VIDEO_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
REASONING_MODEL = "inclusionai/ring-2.6-1t:free"
OVERLAP = 2
TEMPERATURE = 0.2

def video_analysis_model_with_reasoning(content):   
    video_analysis_model_with_reasoning = client.chat.completions.create(
                        model=VIDEO_MODEL,
                        messages=[{"role": "user", "content": content}],
                        temperature=TEMPERATURE,
                        extra_body={"reasoning": {"enabled": True}, "providers": {"quantization": ["int8"]}}
                    )
    return video_analysis_model_with_reasoning

def video_analysis_model_without_reasoning(content):
    video_analysis_model_without_reasoning = client.chat.completions.create(
                        model=VIDEO_MODEL,
                        messages=[{"role": "user", "content": content}],
                        temperature=TEMPERATURE,
                        extra_body={"reasoning": {"enabled": False}, "providers": {"quantization": ["int8"]}}
                    )
    return video_analysis_model_without_reasoning

def reasoning_model_response(timeline: str, user_query: str = None):
    reasoning_model_response = client.chat.completions.create(
                        model=REASONING_MODEL,
                        messages=[{"role": "user", "content": f"Reconstruct the narrative:\n\n{timeline}\n\nQuestion: {user_query or 'Summary'}"}],
                        temperature=TEMPERATURE,
                    )
    return reasoning_model_response