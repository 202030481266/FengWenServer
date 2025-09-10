import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

from jinja2 import Environment, FileSystemLoader

from src.fengwen2.astrology_views import AstrologyResultsView # noqa: F401

logger = logging.getLogger(__name__)


def get_mjml_executable_path() -> str | None:
    home = Path.home()
    if sys.platform == "win32":
        logger.info("Detect Windows System, use default path")
        path = home / "AppData" / "Roaming" / "npm" / "mjml.cmd"
        if not path.exists():
            logger.warning(f"Can't find mjml.cmd at {path}")
            logger.info("Try to find mjml.cmd in system paths")
            mjml_pth = shutil.which("mjml.cmd")
            if mjml_pth:
                path = Path(mjml_pth)
    elif sys.platform == "linux":
        logger.info("Detect Linux System, use default path")
        logger.info("Try to find mjml.cmd in system paths")
        mjml_pth = shutil.which("mjml")
        if mjml_pth:
            logger.info("Find mjml in system paths")
            path = Path(mjml_pth)
        else:
            try:
                node_version = subprocess.run(['node', '-v'], check=True, capture_output=True, text=True)
                node_version = node_version.stdout.strip()
                logger.info(f"Node.js's version: {node_version}")
                path = home / ".nvm" / 'versions' / 'node' / node_version / 'bin' / 'mjml'
            except FileNotFoundError:
                logger.error("Can't find `node` command, may be you need to install the node.js", exc_info=True)
                return None
            except subprocess.CalledProcessError:
                logger.error("Can't run `node` command, please check your node.js", exc_info=True)
                return None
    else:
        logger.error(f"Unsupported platform: {sys.platform}")
        return None
    if path and path.exists():
        logger.info(f"Found mjml executable: {path}")
        return str(path)
    else:
        logger.error(f"Can't find mjml executable path or it is not a file: {path}")
        return None


class MJMLEmailService:
    """
    MJML邮件服务类，处理从mjml.j2模板到HTML邮件的转换
    实际上这个过程非常高效，而且可以使用流水线优化，但是目前的瓶颈在jinja2，所以只需要多线程就行
    测试表现来看一份报告大概就是2到3秒左右
    """

    def __init__(self,
                 template_dir: str = "templates",
                 mjml_command: str = "",
                 mjml_options: Optional[Dict[str, Any]] = None):
        """
        初始化MJML邮件服务

        Args:
            template_dir: 模板文件目录路径
            mjml_command: mjml命令行工具路径，默认为'mjml'（需要全局安装）
            mjml_options: mjml命令行选项
        """
        self.template_dir = Path(template_dir)
        self.mjml_command = mjml_command if mjml_command else get_mjml_executable_path()
        self.mjml_options = mjml_options or {
            "minify": True,
            "beautify": False,
            "validation_level": "soft"
        }

        # 初始化Jinja2环境
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True
        )

        # 验证mjml命令是否可用
        self._verify_mjml_installation()

    def _verify_mjml_installation(self):
        try:
            result = subprocess.run(
                [self.mjml_command, "--version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8"
            )
            logger.info(f"MJML version: {result.stdout.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(
                f"MJML command '{self.mjml_command}' not found. "
                "Please install it using: npm install -g mjml"
            )

    def render_template_to_mjml(self,
                                template_name: str,
                                context: Dict[str, Any]) -> str:
        """
        使用Jinja2渲染MJML模板

        Args:
            template_name: 模板文件名（如：'astrology_report.mjml.j2'）
            context: 渲染上下文数据

        Returns:
            渲染后的MJML内容
        """
        try:
            template = self.jinja_env.get_template(template_name)
            mjml_content = template.render(**context)
            logger.debug(f"Successfully rendered template: {template_name}")
            return mjml_content
        except Exception as e:
            logger.error(f"Failed to render template {template_name}: {str(e)}", exc_info=True)
            raise

    def convert_mjml_to_html(self, mjml_content: str) -> str:
        """
        使用MJML命令行工具将MJML转换为HTML

        Args:
            mjml_content: MJML内容字符串

        Returns:
            转换后的HTML内容
        """
        with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.mjml',
                delete=False,
                encoding='utf-8'
        ) as temp_mjml:
            temp_mjml.write(mjml_content)
            temp_mjml_path = temp_mjml.name

        try:
            cmd = [self.mjml_command, temp_mjml_path]
            if self.mjml_options.get("minify"):
                cmd.append("--config.minify=true")
            if self.mjml_options.get("beautify"):
                cmd.append("--config.beautify=true")
            if self.mjml_options.get("validation_level"):
                cmd.extend(["-l", self.mjml_options["validation_level"]])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )

            if result.stderr:
                logger.warning(f"MJML warnings: {result.stderr}")

            logger.debug("Successfully converted MJML to HTML")
            return result.stdout

        except subprocess.CalledProcessError as e:
            stderr_decoded = e.stderr if isinstance(e.stderr, str) else e.stderr.decode('utf-8', errors='replace')
            logger.error(f"MJML conversion failed: {stderr_decoded}", exc_info=True)
            raise RuntimeError(f"Failed to convert MJML to HTML: {stderr_decoded}")
        finally:
            if os.path.exists(temp_mjml_path):
                os.unlink(temp_mjml_path)

    def render_email(self,
                     template_name: str,
                     astrology_results: 'AstrologyResultsView',
                     additional_context: Optional[Dict[str, Any]] = None) -> str:
        """
        完整的邮件渲染流程：从模板到最终HTML

        Args:
            template_name: 模板文件名
            astrology_results: 占星结果数据对象
            additional_context: 额外的上下文数据

        Returns:
            最终的HTML邮件内容
        """
        context = {
            "bazi": astrology_results.bazi,
            "liudao": astrology_results.liudao,
            "zhengyuan": astrology_results.zhengyuan
        }

        if additional_context:
            context.update(additional_context)

        # use jinja2 render the mjml html
        mjml_content = self.render_template_to_mjml(template_name, context)

        # turn mjml html into email html
        html_content = self.convert_mjml_to_html(mjml_content)

        return html_content

    def render_and_save(self,
                        template_name: str,
                        astrology_results: 'AstrologyResultsView',
                        output_path: str,
                        additional_context: Optional[Dict[str, Any]] = None) -> str:
        """
        渲染邮件并保存到文件

        Args:
            template_name: 模板文件名
            astrology_results: 占星结果数据对象
            output_path: 输出文件路径
            additional_context: 额外的上下文数据

        Returns:
            输出文件的绝对路径
        """
        html_content = self.render_email(
            template_name,
            astrology_results,
            additional_context
        )

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Email HTML saved to: {output_file.absolute()}")
        return str(output_file.absolute())
