# token_service.py
import os
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import logging
import asyncio
from urllib.parse import urlencode
import base64

from playwright.async_api import async_playwright, Browser, Page
from PIL import Image
from io import BytesIO
import httpx

logger = logging.getLogger(__name__)


class TokenService:
    """Token生成和验证服务"""

    def __init__(self):
        self.secret_key = os.getenv("TOKEN_SECRET_KEY", secrets.token_urlsafe(32))
        self.tokens = {}  # 存储token及其相关信息
        self.token_expiry = timedelta(hours=24)  # Token有效期24小时

    def generate_token(self, record_id: int, email: str) -> str:
        """生成安全token"""
        # 生成唯一token
        token_data = f"{record_id}:{email}:{datetime.now().isoformat()}:{secrets.token_urlsafe(16)}"
        token = hashlib.sha256(token_data.encode()).hexdigest()

        # 存储token信息
        self.tokens[token] = {
            "record_id": record_id,
            "email": email,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + self.token_expiry,
            "used": False
        }

        logger.info(f"Generated token for record {record_id}, email {email}")
        return token

    def verify_token(self, token: str) -> Tuple[bool, Optional[Dict]]:
        """验证token是否有效"""
        if token not in self.tokens:
            logger.warning(f"Token not found: {token}")
            return False, None

        token_data = self.tokens[token]

        # 检查是否过期
        if datetime.now() > token_data["expires_at"]:
            logger.warning(f"Token expired: {token}")
            del self.tokens[token]
            return False, None

        # 检查是否已使用（可选：允许多次使用）
        if token_data["used"] and not os.getenv("ALLOW_TOKEN_REUSE", "false").lower() == "true":
            logger.warning(f"Token already used: {token}")
            return False, None

        # 标记为已使用
        self.tokens[token]["used"] = True
        self.tokens[token]["last_used"] = datetime.now()

        logger.info(f"Token verified successfully for record {token_data['record_id']}")
        return True, token_data

    def cleanup_expired_tokens(self):
        """清理过期的tokens"""
        now = datetime.now()
        expired_tokens = [
            token for token, data in self.tokens.items()
            if now > data["expires_at"]
        ]
        for token in expired_tokens:
            del self.tokens[token]

        if expired_tokens:
            logger.info(f"Cleaned up {len(expired_tokens)} expired tokens")


class ScreenshotService:
    """使用Playwright进行网页截图服务"""

    def __init__(self):
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.browser: Optional[Browser] = None
        self.viewport = {"width": 1920, "height": 1080}  # 默认视窗大小
        self.timeout = 30000  # 30秒超时

    async def initialize(self):
        """初始化浏览器"""
        if not self.browser:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            logger.info("Browser initialized")

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            self.browser = None
            logger.info("Browser closed")

    async def capture_full_report(
            self,
            token: str,
            record_id: int,
            output_format: str = "both"  # "image", "pdf", or "both"
    ) -> Dict[str, bytes]:
        """
        捕获完整报告

        Args:
            token: 验证token
            record_id: 记录ID
            output_format: 输出格式

        Returns:
            包含图片和/或PDF的字典
        """
        await self.initialize()

        page = None
        try:
            # 创建新页面
            context = await self.browser.new_context(
                viewport=self.viewport,
                device_scale_factor=2,  # 高DPI截图
            )
            page = await context.new_page()

            # 构建带token的URL
            url = f"{self.frontend_url}/report?token={token}&record_id={record_id}&full=true"
            logger.info(f"Loading report page: {url}")

            # 导航到页面
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)

            # 等待内容完全加载（可根据前端实际情况调整选择器）
            await page.wait_for_selector(".report-content", timeout=self.timeout)

            # 可选：等待所有图片加载
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)  # 额外等待动画完成

            # 隐藏不需要的元素（如导航栏、按钮等）
            await self._hide_unnecessary_elements(page)

            results = {}

            # 截图
            if output_format in ["image", "both"]:
                screenshot_bytes = await self._capture_screenshot(page)
                results["image"] = screenshot_bytes
                logger.info(f"Screenshot captured, size: {len(screenshot_bytes)} bytes")

            # 生成PDF
            if output_format in ["pdf", "both"]:
                pdf_bytes = await self._generate_pdf(page)
                results["pdf"] = pdf_bytes
                logger.info(f"PDF generated, size: {len(pdf_bytes)} bytes")

            return results

        except Exception as e:
            logger.error(f"Error capturing report: {e}")
            raise
        finally:
            if page:
                await page.close()

    async def _hide_unnecessary_elements(self, page: Page):
        """隐藏不必要的页面元素"""
        try:
            # 注入CSS隐藏特定元素
            await page.add_style_tag(content="""
                .navbar, .footer, .unlock-button, .payment-button, 
                .advertisement, .cookie-notice, .chat-widget {
                    display: none !important;
                }

                /* 确保内容全部显示 */
                .locked-content, .premium-content {
                    display: block !important;
                    opacity: 1 !important;
                }

                /* 移除水印或遮罩 */
                .watermark, .overlay {
                    display: none !important;
                }

                /* 优化打印样式 */
                body {
                    background: white !important;
                    padding: 20px !important;
                }
            """)

            # 可选：执行JavaScript移除元素
            await page.evaluate("""
                () => {
                    // 移除所有按钮
                    document.querySelectorAll('button').forEach(el => el.remove());

                    // 展开所有折叠内容
                    document.querySelectorAll('[data-collapsed="true"]').forEach(el => {
                        el.setAttribute('data-collapsed', 'false');
                    });
                }
            """)
        except Exception as e:
            logger.warning(f"Error hiding elements: {e}")

    async def _capture_screenshot(self, page: Page) -> bytes:
        """捕获页面截图"""
        # 获取完整页面截图
        screenshot = await page.screenshot(
            full_page=True,
            type='png',
            quality=100,
            animations='disabled'
        )

        # 可选：压缩图片
        compressed = self._compress_image(screenshot)
        return compressed

    async def _generate_pdf(self, page: Page) -> bytes:
        """生成PDF文档"""
        pdf = await page.pdf(
            format='A4',
            print_background=True,
            margin={
                'top': '20px',
                'right': '20px',
                'bottom': '20px',
                'left': '20px'
            },
            display_header_footer=False,
            prefer_css_page_size=True
        )
        return pdf

    def _compress_image(self, image_bytes: bytes, max_size_mb: float = 5) -> bytes:
        """压缩图片"""
        try:
            # 打开图片
            img = Image.open(BytesIO(image_bytes))

            # 如果图片太大，进行压缩
            output = BytesIO()
            quality = 95

            while quality > 30:
                output.seek(0)
                output.truncate()
                img.save(output, format='PNG', optimize=True, quality=quality)
                size_mb = len(output.getvalue()) / (1024 * 1024)

                if size_mb <= max_size_mb:
                    break

                quality -= 5

            return output.getvalue()

        except Exception as e:
            logger.warning(f"Image compression failed: {e}")
            return image_bytes


class ReportEmailService:
    """发送包含截图报告的邮件服务"""

    def __init__(self, email_service):
        self.email_service = email_service
        self.token_service = TokenService()
        self.screenshot_service = ScreenshotService()

    async def process_payment_completion(self, record_id: int, email: str, name: str):
        """
        处理支付完成后的流程

        1. 生成token
        2. 截图
        3. 发送邮件
        """
        try:
            # Step 1: 生成token
            token = self.token_service.generate_token(record_id, email)
            logger.info(f"Token generated for record {record_id}")

            # Step 2: 获取截图和PDF
            report_files = await self.screenshot_service.capture_full_report(
                token=token,
                record_id=record_id,
                output_format="both"
            )

            # Step 3: 发送邮件
            success = await self._send_report_email(
                email=email,
                name=name,
                report_files=report_files,
                record_id=record_id
            )

            if success:
                logger.info(f"Report email sent successfully to {email}")
            else:
                logger.error(f"Failed to send report email to {email}")
                # 可以加入重试队列

            return success

        except Exception as e:
            logger.error(f"Error processing payment completion: {e}")
            return False

    async def _send_report_email(
            self,
            email: str,
            name: str,
            report_files: Dict[str, bytes],
            record_id: int
    ) -> bool:
        """发送包含报告的邮件"""
        try:
            # 准备附件
            attachments = []

            if "image" in report_files:
                attachments.append({
                    "filename": f"astrology_report_{record_id}.png",
                    "content": base64.b64encode(report_files["image"]).decode(),
                    "content_type": "image/png"
                })

            if "pdf" in report_files:
                attachments.append({
                    "filename": f"astrology_report_{record_id}.pdf",
                    "content": base64.b64encode(report_files["pdf"]).decode(),
                    "content_type": "application/pdf"
                })

            # 使用现有的邮件服务发送（需要修改以支持附件）
            # 这里需要根据你的腾讯云SES配置来调整
            email_content = f"""
            Dear {name},

            Thank you for your purchase! Your personalized astrology reading is attached.

            You can view your report in the attached files:
            - PNG image for quick viewing
            - PDF document for printing or saving

            Best regards,
            Your Astrology Team
            """

            # 调用邮件服务（需要修改email_service以支持附件）
            return await self._send_with_attachments(
                email,
                name,
                email_content,
                attachments
            )

        except Exception as e:
            logger.error(f"Error sending report email: {e}")
            return False

    async def _send_with_attachments(
            self,
            email: str,
            name: str,
            content: str,
            attachments: list
    ) -> bool:
        """发送带附件的邮件（需要更新腾讯云SES配置）"""
        # 这里需要更新你的email_service.py来支持附件
        # 腾讯云SES支持通过RawMessage发送带附件的邮件

        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            import base64

            # 创建邮件消息
            msg = MIMEMultipart()
            msg['From'] = f"noreply@{self.email_service.domain}"
            msg['To'] = email
            msg['Subject'] = "Your Astrology Reading Report"

            # 添加正文
            msg.attach(MIMEText(content, 'plain'))

            # 添加附件
            for attachment in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(base64.b64decode(attachment['content']))
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={attachment["filename"]}'
                )
                msg.attach(part)

            # 发送邮件（需要使用腾讯云的SendRawEmail API）
            # 这里简化处理，实际需要调用腾讯云API
            logger.info(f"Email with attachments prepared for {email}")
            return True

        except Exception as e:
            logger.error(f"Error creating email with attachments: {e}")
            return False