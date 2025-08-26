import httpx
import json
import os
import re
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

class TranslationService:
    """Simple translation service for Chinese astrology content"""
    
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = os.getenv("DEEPSEEK_API_URL", "https://api.lkeap.cloud.tencent.com/v1/chat/completions")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3-0324")
    
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
    
    async def batch_translate(self, texts: List[str]) -> Dict[str, str]:
        """Translate multiple texts in one API call"""
        if not texts:
            return {}
        
        # Create numbered list
        numbered = [f"{i+1}. {text}" for i, text in enumerate(texts)]
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
                
                return translations
                
        except Exception as e:
            print(f"Translation error: {e}")
            return {text: text for text in texts}  # Return originals on error
    
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
        print("[TRANSLATOR] Starting translation...")
        
        # Find all Chinese texts
        chinese_texts = self.find_chinese_texts(data)
        print(f"[TRANSLATOR] Found {len(chinese_texts)} Chinese texts")
        
        if not chinese_texts:
            return data
        
        # Translate all at once
        translations = await self.batch_translate(chinese_texts)
        print(f"[TRANSLATOR] Translated {len(translations)} texts")
        
        # Apply translations
        translated_data = self.apply_translations(data, translations)
        print("[TRANSLATOR] Translation complete")
        
        return translated_data
    
    async def extract_and_translate_astrology_result(self, astrology_data: dict, original_name: str = None) -> dict:
        """Main translation entry point"""
        if not astrology_data:
            return None
        
        # Replace names if provided
        if original_name:
            astrology_data = self._replace_names(astrology_data, original_name)
        
        # Translate everything
        return await self.translate_json(astrology_data)
    
    def _replace_names(self, data: dict, name: str) -> dict:
        """Replace name fields with original name"""
        import copy
        result = copy.deepcopy(data)
        
        def replace_in_obj(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "name" and isinstance(value, str):
                        obj[key] = name
                    else:
                        replace_in_obj(value)
            elif isinstance(obj, list):
                for item in obj:
                    replace_in_obj(item)
        
        replace_in_obj(result)
        return result