import os
import json
import base64
import requests


def create_image(prompt: str, api_key: str, size: str = "1024x1024", model: str = "gpt-image-2"):
    url = "https://api.jucode.cn/v1/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    API_KEY = ""
    prompt_text = "唐僧被如来佛祖请去喝茶，中国神话插画风格"

    try:
        result = create_image(prompt_text, API_KEY)
        print("生成成功！")

        # 保存 base64 图片
        b64_json = result["data"][0]["b64_json"]
        output_path = os.path.join(os.path.dirname(__file__), "output.png")
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(b64_json))
        print(f"图片已保存到: {output_path}")

    except requests.exceptions.HTTPError as e:
        print(f"HTTP错误: {e.response.status_code}")
        print(e.response.text)
    except Exception as e:
        print(f"请求失败: {e}")
