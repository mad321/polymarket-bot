import logging
from typing import Dict, Optional
from config import (
    CLAUDE_API_KEY,
    GEMINI_API_KEY,
    CLAUDE_MODEL,
    GEMINI_MODEL,
    MAX_TOKENS
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIAnalyzer:
    """فئة تحليل السوق باستخدام نماذج الذكاء الاصطناعي"""

    def build_analysis_prompt(self, market_data: Dict) -> str:
        """بناء مطالبة تحليلية بناءً على بيانات السوق الحقيقية"""
        question = market_data.get("question", "")
        prices = market_data.get("prices", {})
        volume = market_data.get("volume", 0)
        volume_7d = market_data.get("volume_7d", 0)
        liquidity = market_data.get("total_liquidity", 0)
        time_remaining = market_data.get("time_remaining_seconds", 0)

        hours_remaining = time_remaining / 3600
        days_remaining = hours_remaining / 24

        prompt = f"""أنت خبير تداول متخصص في أسواق التنبؤ على Polymarket.

بيانات السوق الحية:
- السؤال: {question}
- الأسعار الحالية: {prices}
- السيولة الإجمالية: ${liquidity:.2f}
- الحجم (24 ساعة): ${volume:.2f}
- الحجم (7 أيام): ${volume_7d:.2f}
- الوقت المتبقي: {days_remaining:.2f} يوم ({hours_remaining:.1f} ساعة)

بناءً على هذه البيانات:
1. ما هو احتمالية النتيجة الأكثر ترجيحاً؟
2. ما هو أفضل خيار للشراء الآن (السعر الأقل مخاطرة)؟
3. ما هو العائد المتوقع إذا سار السوق لصالحك؟
4. ما هي المخاطر الرئيسية التي يجب الانتباه لها؟

أعطِ إجابة موجزة وعملية (بحد أقصى 150 كلمة)."""

        return prompt

    def get_claude_analysis(self, market_data: Dict) -> Dict:
        """تحليل السوق باستخدام Claude Haiku"""
        if not CLAUDE_API_KEY:
            return {
                "status": "error",
                "message": "مفتاح Claude API غير مسجل",
                "analysis": None
            }

        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=CLAUDE_API_KEY)
            prompt = self.build_analysis_prompt(market_data)

            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            analysis_text = message.content[0].text
            logger.info("✅ تم الحصول على تحليل Claude بنجاح")

            return {
                "status": "success",
                "model": "Claude Haiku",
                "analysis": analysis_text,
                "tokens_used": message.usage.input_tokens + message.usage.output_tokens
            }

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل Claude: {e}")
            return {
                "status": "error",
                "message": str(e),
                "analysis": None
            }

    def get_gemini_analysis(self, market_data: Dict) -> Dict:
        """تحليل السوق باستخدام Gemini Flash"""
        if not GEMINI_API_KEY:
            return {
                "status": "error",
                "message": "مفتاح Gemini API غير مسجل",
                "analysis": None
            }

        try:
            import google.generativeai as genai

            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel(GEMINI_MODEL)
            prompt = self.build_analysis_prompt(market_data)

            response = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": MAX_TOKENS,
                    "temperature": 0.7,
                }
            )

            analysis_text = response.text
            logger.info("✅ تم الحصول على تحليل Gemini بنجاح")

            return {
                "status": "success",
                "model": "Gemini Flash",
                "analysis": analysis_text,
                "tokens_used": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0
            }

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل Gemini: {e}")
            return {
                "status": "error",
                "message": str(e),
                "analysis": None
            }

    def analyze_market(self, market_data: Dict) -> Dict:
        """تحليل السوق باستخدام كلا النموذجين"""
        return {
            "claude": self.get_claude_analysis(market_data),
            "gemini": self.get_gemini_analysis(market_data)
        }
