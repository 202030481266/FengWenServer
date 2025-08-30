import asyncio
import logging
import os
import re
from typing import Dict, Any, List

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class TranslationService:
    """Simple translation service for Chinese astrology content with concurrent processing"""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = os.getenv("DEEPSEEK_API_URL", "https://api.lkeap.cloud.tencent.com/v1/chat/completions")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3-0324")
        self.max_concurrent = 32
        self.batch_size = 2

    @staticmethod
    def has_chinese(text: str) -> bool:
        """Check if text contains Chinese characters"""
        return any('\u4e00' <= c <= '\u9fff' for c in text)

    def find_chinese_texts(self, obj: Any) -> List[str]:
        """Find all Chinese text in JSON structure"""
        texts = []

        def extract(data):
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(key, str) and self.has_chinese(key) and key.strip():
                        texts.append(key.strip())
                    extract(value)
            elif isinstance(data, list):
                for item in data:
                    extract(item)
            elif isinstance(data, str) and self.has_chinese(data) and data.strip():
                lines = data.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if self.has_chinese(line) and line:
                        texts.append(line)
                if self.has_chinese(data.strip()):
                    texts.append(data.strip())

        extract(obj)
        return list(dict.fromkeys(text for text in texts if text.strip()))

    async def translate_batch(self, texts: List[str], semaphore: asyncio.Semaphore) -> Dict[str, str]:
        """Translate a small batch of texts in one API call"""
        if not texts:
            return {}

        async with semaphore:  # 控制并发数
            # Create numbered list
            numbered = [f"{i + 1}. {text}" for i, text in enumerate(texts)]
            batch_text = "\n\n".join(numbered)

            system_prompt = """You are a professional Chinese-English translator for traditional astrology.

RULES:
1. Translate ALL numbered items EXACTLY - no explanations, no additions
2. Return in same format: "1. [translation]", "2. [translation]", etc.
3. Translate completely - no Chinese characters left
4. Keep mystical fortune-telling tone
5. Use proper astrology terms

Terms:
- 乾造 = Male Fortune
- 坤造 = Female Fortune  
- 正印 = Direct Seal
- 偏印 = Indirect Seal
- 正官 = Direct Officer
- 五行 = Five Elements
- 八字 = Eight Characters

Only return numbered translations."""

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Translate:\n\n{batch_text}"}
                ],
                "temperature": 0.3,
                "top_p": 0.8,
                "max_tokens": 2048
            }

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(self.api_url, headers=headers, json=payload)
                    response.raise_for_status()
                    result = response.json()["choices"][0]["message"]["content"]

                    # Parse results
                    translations = {}
                    for line in result.split('\n'):
                        match = re.match(r'^(\d+)\.\s+(.+)', line.strip())
                        if match:
                            index = int(match.group(1)) - 1
                            translation = match.group(2).strip()
                            if index < len(texts):
                                translations[texts[index]] = translation

                    # 补充缺失的翻译（使用原文）
                    for text in texts:
                        if text not in translations:
                            logger.warning(f"Translation missing for: {text[:50]}...")
                            translations[text] = text

                    return translations

            except Exception as e:
                logger.error(f"Translation API error for batch: {e}")
                return {text: text for text in texts}  # Return originals on error

    async def batch_translate(self, texts: List[str]) -> Dict[str, str]:
        """Translate multiple texts using concurrent API calls"""
        if not texts:
            return {}

        logger.info(f"Starting concurrent translation for {len(texts)} texts...")

        semaphore = asyncio.Semaphore(self.max_concurrent)
        batches = []
        texts_list = list(texts)  # 确保是列表
        for i in range(0, len(texts_list), self.batch_size):
            batch = texts_list[i:i + self.batch_size]
            batches.append(batch)

        logger.info(f"Split into {len(batches)} batches of up to {self.batch_size} texts each")

        tasks = [self.translate_batch(batch, semaphore) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        all_translations = {}
        for batch_result in batch_results:
            all_translations.update(batch_result)

        logger.info(f"Completed translation of {len(all_translations)} texts")
        return all_translations

    def apply_translations(self, obj: Any, translations: Dict[str, str]) -> Any:
        """Apply translations to JSON structure"""
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                new_key = translations.get(k.strip(), k) if isinstance(k, str) and self.has_chinese(k) else k
                result[new_key] = self.apply_translations(v, translations)
            return result
        elif isinstance(obj, list):
            return [self.apply_translations(item, translations) for item in obj]
        elif isinstance(obj, str) and self.has_chinese(obj):
            if obj.strip() in translations:
                return translations[obj.strip()]

            lines = obj.split('\n')
            translated_lines = [translations.get(line.strip(), line) for line in lines]

            if translated_lines != [line.strip() for line in lines]:
                return '\n'.join(translated_lines)
            return obj
        return obj

    async def translate_json(self, data: dict) -> dict:
        """Translate entire JSON structure while preserving format"""
        logger.info("Starting translation process...")

        # Find all Chinese texts
        chinese_texts = self.find_chinese_texts(data)
        if not chinese_texts:
            logger.info("No Chinese text found. Skipping translation.")
            return data

        logger.info(f"Found {len(chinese_texts)} unique Chinese texts to translate.")

        # Translate with concurrency
        translations = await self.batch_translate(chinese_texts)
        if len(translations) < len(chinese_texts):
            logger.warning(f"Translation may be incomplete. Expected {len(chinese_texts)} but got {len(translations)}.")
        else:
            logger.info(f"Successfully translated {len(translations)} texts.")

        # Apply translations
        translated_data = self.apply_translations(data, translations)
        logger.info("Translation process complete.")

        return translated_data

    async def extract_and_translate_astrology_result(self, astrology_data: dict) -> dict | None:
        """Main translation entry point"""
        if not astrology_data:
            return None
        return await self.translate_json(astrology_data)