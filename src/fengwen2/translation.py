import asyncio
import logging
import os
import re
from collections import Counter
from typing import Dict, Any, List, Optional

import httpx
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.fengwen2.admin_models import TranslationPair

logger = logging.getLogger(__name__)

load_dotenv()


class TranslationTermsManager:
    """管理翻译术语对，包括从数据库加载和智能选择"""

    def __init__(self):
        self.all_terms: Dict[str, str] = {}
        self.term_frequency: Counter = Counter()
        self.max_terms_in_prompt = 100  # 提示词中最多包含的术语数
        self.cache_ttl = 3600  # 1 hour
        self.last_cache_time = 0

    async def load_from_database(self, db: AsyncSession) -> Dict[str, str]:
        """从数据库加载所有翻译对"""
        try:
            result = await db.execute(select(TranslationPair))
            pairs = result.scalars().all()

            self.all_terms = {}
            for pair in pairs:
                """
                这里考虑的可能的数据形式是：
                中文：
                    苹果
                    香蕉
                    土豆
                英文：
                    apple
                    banana
                    potato
                """
                chinese_lines = pair.chinese_text.strip().split('\n')
                english_lines = pair.english_text.strip().split('\n')

                # 如果行数匹配，逐行对应才进行翻译
                if len(chinese_lines) == len(english_lines):
                    for ch, en in zip(chinese_lines, english_lines):
                        ch = ch.strip()
                        en = en.strip()
                        if ch and en:
                            self.all_terms[ch] = en
                else:
                    # 否则作为整体处理
                    self.all_terms[pair.chinese_text.strip()] = pair.english_text.strip()

            logger.info(f"Loaded {len(self.all_terms)} translation pairs from database")
            return self.all_terms

        except Exception as e:
            logger.error(f"Error loading translation pairs: {e}")
            return {}

    def find_relevant_terms(self, texts: List[str]) -> Dict[str, str]:
        """找出与待翻译文本相关的术语，就是简单的判断字符串匹配次数"""
        relevant_terms = {}

        # 统计文本中的词频
        all_text = ' '.join(texts)

        for chinese_term, english_term in self.all_terms.items():
            # 检查术语是否出现在文本中
            if chinese_term in all_text:
                relevant_terms[chinese_term] = english_term
                # 统计出现频率
                count = sum(1 for text in texts if chinese_term in text)
                self.term_frequency[chinese_term] = count

        return relevant_terms

    def select_terms_for_prompt(self, texts: List[str]) -> Dict[str, str]:
        """智能选择要包含在提示词中的术语"""
        relevant_terms = self.find_relevant_terms(texts)

        if len(relevant_terms) <= self.max_terms_in_prompt:
            # 如果相关术语不多，全部使用
            logger.info(f"Using all {len(relevant_terms)} relevant terms in prompt")
            return relevant_terms

        # 如果术语太多，按以下策略选择：
        # 1. 优先选择高频出现的术语
        # 2. 优先选择较短的术语（通常是更基础的词汇）
        # 3. 确保包含一些长短语（可能是专业术语）

        scored_terms = []
        for term, translation in relevant_terms.items():
            frequency = self.term_frequency.get(term, 0)
            length_score = 1 / (1 + len(term) / 10)  # 长度分数，越短分数越高
            is_phrase = len(term) > 4  # 是否是短语

            # 综合评分
            score = frequency * 2 + length_score
            if is_phrase and frequency > 0:
                score += 0.5  # 给出现的短语加分

            scored_terms.append((score, term, translation))

        # 按分数排序，选择前N个
        scored_terms.sort(reverse=True)
        selected = {}

        # 确保有一定的多样性
        short_count = 0
        long_count = 0

        for score, term, translation in scored_terms:
            if len(selected) >= self.max_terms_in_prompt:
                break

            # 保持短术语和长术语的平衡
            if len(term) <= 4:
                if short_count < self.max_terms_in_prompt * 0.7:
                    selected[term] = translation
                    short_count += 1
            else:
                if long_count < self.max_terms_in_prompt * 0.3:
                    selected[term] = translation
                    long_count += 1

        logger.info(f"Selected {len(selected)} terms from {len(relevant_terms)} relevant terms")
        return selected


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


class EnhancedTranslationService:
    """增强版翻译服务，集成数据库术语"""

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = os.getenv("DEEPSEEK_API_URL", "https://api.lkeap.cloud.tencent.com/v1/chat/completions")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3-0324")
        self.max_concurrent = 32
        self.batch_size = 2
        self.terms_manager = TranslationTermsManager()
        self.db_session: Optional[AsyncSession] = None

    def set_db_session(self, session: AsyncSession):
        """设置数据库会话"""
        self.db_session = session

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

    @staticmethod
    def build_system_prompt(custom_terms: Dict[str, str]) -> str:
        """构建包含自定义术语的系统提示词"""
        base_prompt = """You are a professional Chinese-English translator for traditional astrology.

RULES:
1. Translate ALL numbered items EXACTLY - no explanations, no additions
2. Return in same format: "1. [translation]", "2. [translation]", etc.
3. Translate completely - no Chinese characters left
4. Keep mystical fortune-telling tone
5. Use proper astrology terms
6. IMPORTANT: Use the provided custom terms EXACTLY as given when you encounter them"""

        # 添加基础术语
        base_terms = {
            "乾造": "Male Fortune",
            "坤造": "Female Fortune",
            "正印": "Direct Seal",
            "偏印": "Indirect Seal",
            "正官": "Direct Officer",
            "五行": "Five Elements",
            "八字": "Eight Characters"
        }

        # 合并自定义术语
        all_terms = {**base_terms, **custom_terms}

        if not custom_terms:
            # 如果没有自定义术语，使用原始提示词
            terms_section = "\n".join([f"- {ch} = {en}" for ch, en in base_terms.items()])
        else:
            # 格式化术语列表
            terms_list = []

            # 如果术语不多，详细列出
            if len(all_terms) <= 50:
                for chinese, english in all_terms.items():
                    terms_list.append(f"- {chinese} = {english}")
                terms_section = "\n".join(terms_list)
            else:
                # 如果术语很多，分组显示
                # 短术语（基础词汇）
                short_terms = {k: v for k, v in all_terms.items() if len(k) <= 4}
                long_terms = {k: v for k, v in all_terms.items() if len(k) > 4}

                terms_section = "Common Terms:\n"
                terms_section += "\n".join([f"- {ch} = {en}" for ch, en in list(short_terms.items())[:30]])

                if long_terms:
                    terms_section += "\n\nSpecialized Phrases:\n"
                    terms_section += "\n".join([f"- {ch} = {en}" for ch, en in list(long_terms.items())[:20]])

        full_prompt = f"""{base_prompt}

Terms to use:
{terms_section}

Only return numbered translations."""

        return full_prompt

    async def translate_batch(
            self,
            texts: List[str],
            semaphore: asyncio.Semaphore,
            custom_terms: Dict[str, str]
    ) -> Dict[str, str]:
        """Translate a small batch of texts in one API call with custom terms"""
        if not texts:
            return {}

        async with semaphore:
            numbered = [f"{i + 1}. {text}" for i, text in enumerate(texts)]
            batch_text = "\n\n".join(numbered)

            # 使用包含自定义术语的提示词
            system_prompt = self.build_system_prompt(custom_terms)

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

                    translations = {}
                    for line in result.split('\n'):
                        match = re.match(r'^(\d+)\.\s+(.+)', line.strip())
                        if match:
                            index = int(match.group(1)) - 1
                            translation = match.group(2).strip()
                            if index < len(texts):
                                translations[texts[index]] = translation

                    # 补充缺失的翻译
                    for text in texts:
                        if text not in translations:
                            # 尝试使用自定义术语直接翻译
                            if text in custom_terms:
                                translations[text] = custom_terms[text]
                            else:
                                logger.warning(f"Translation missing for: {text[:50]}...")
                                translations[text] = text

                    return translations

            except Exception as e:
                logger.error(f"Translation API error for batch: {e}")
                # 失败时尝试使用自定义术语，回退策略
                return {text: custom_terms.get(text, text) for text in texts}

    async def batch_translate(self, texts: List[str]) -> Dict[str, str]:
        """Translate multiple texts using concurrent API calls with database terms"""
        if not texts:
            return {}

        logger.info(f"Starting concurrent translation for {len(texts)} texts...")

        # 加载数据库术语（如果有数据库会话）
        custom_terms = {}
        if self.db_session:
            await self.terms_manager.load_from_database(self.db_session)
            # 选择相关术语
            custom_terms = self.terms_manager.select_terms_for_prompt(texts)
            logger.info(f"Using {len(custom_terms)} custom terms from database")

        semaphore = asyncio.Semaphore(self.max_concurrent)
        batches = []
        texts_list = list(texts)
        for i in range(0, len(texts_list), self.batch_size):
            batch = texts_list[i:i + self.batch_size]
            batches.append(batch)

        logger.info(f"Split into {len(batches)} batches of up to {self.batch_size} texts each")

        tasks = [self.translate_batch(batch, semaphore, custom_terms) for batch in batches]
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

    async def extract_and_translate_astrology_result(self, astrology_data: dict,
                                                     db_session: Optional[AsyncSession] = None) -> dict | None:
        """Main translation entry point with optional database session"""
        if not astrology_data:
            return None

        if db_session:
            self.db_session = db_session

        return await self.translate_json(astrology_data)
