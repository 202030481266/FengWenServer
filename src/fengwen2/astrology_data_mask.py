from src.fengwen2.astrology_views import (
    AstrologyApiResponseView,
    ApiLiudaoResponseView,
    ApiZhengyuanResponseView,
    LiudaoInfoItemView,
    HuaxiangInfoView,
    TezhiInfoView,
    ZhiyinInfoView
)


class AstrologyDataMaskingService:
    """占卜数据脱敏服务"""

    MASK_CHAR = "*"
    PREVIEW_LENGTH = 20  # 预览字符长度
    TEASER_TEXT = "...解锁查看完整内容"

    @staticmethod
    def mask_text(text: str, preview_length: int = 20, mask_ratio: float = 0.7) -> str:
        """
        对文本进行脱敏处理

        Args:
            text: 原始文本
            preview_length: 预览长度
            mask_ratio: 遮蔽比例 (0-1)

        Returns:
            脱敏后的文本
        """
        if not text or len(text) <= preview_length:
            return text

        preview = text[:preview_length]
        remaining_length = len(text) - preview_length
        mask_length = int(remaining_length * mask_ratio)

        masked_text = preview + AstrologyDataMaskingService.MASK_CHAR * min(mask_length,
                                                                            10) + AstrologyDataMaskingService.TEASER_TEXT

        return masked_text

    @staticmethod
    def mask_liudao_item(item: LiudaoInfoItemView) -> LiudaoInfoItemView:
        """对六道信息项进行脱敏"""
        masked_item = item.model_copy()

        # 保留名称和简单描述，脱敏详细描述
        masked_item.liudao_detail_desc = AstrologyDataMaskingService.mask_text(
            item.liudao_detail_desc,
            preview_length=30
        )

        return masked_item

    @staticmethod
    def mask_liudao_response(response: ApiLiudaoResponseView) -> ApiLiudaoResponseView:
        """对六道轮回响应进行脱敏"""
        if not response.data or not response.data.liudao_info:
            return response

        masked_response = response.model_copy(deep=True)
        liudao_details = masked_response.data.liudao_info.liudao_info

        # 脱敏过去、现在、未来的信息
        liudao_details.past_info = AstrologyDataMaskingService.mask_liudao_item(liudao_details.past_info)
        liudao_details.now_info = AstrologyDataMaskingService.mask_liudao_item(liudao_details.now_info)
        liudao_details.future_info = AstrologyDataMaskingService.mask_liudao_item(liudao_details.future_info)

        return masked_response

    @staticmethod
    def mask_huaxiang(huaxiang: HuaxiangInfoView) -> HuaxiangInfoView:
        """对真爱画像进行脱敏"""
        masked = huaxiang.model_copy()

        # 对各个特征进行部分脱敏
        masked.face_shape = AstrologyDataMaskingService.mask_text(huaxiang.face_shape, preview_length=10)
        masked.eyebrow_shape = AstrologyDataMaskingService.mask_text(huaxiang.eyebrow_shape, preview_length=10)
        masked.eye_shape = AstrologyDataMaskingService.mask_text(huaxiang.eye_shape, preview_length=10)
        masked.mouth_shape = AstrologyDataMaskingService.mask_text(huaxiang.mouth_shape, preview_length=10)
        masked.nose_shape = AstrologyDataMaskingService.mask_text(huaxiang.nose_shape, preview_length=10)
        masked.body_shape = AstrologyDataMaskingService.mask_text(huaxiang.body_shape, preview_length=10)

        return masked

    @staticmethod
    def mask_tezhi(tezhi: TezhiInfoView) -> TezhiInfoView:
        """对真爱特质进行脱敏"""
        masked = tezhi.model_copy()

        masked.romantic_personality = AstrologyDataMaskingService.mask_text(tezhi.romantic_personality,
                                                                            preview_length=25)
        masked.family_background = AstrologyDataMaskingService.mask_text(tezhi.family_background, preview_length=25)
        masked.career_wealth = AstrologyDataMaskingService.mask_text(tezhi.career_wealth, preview_length=25)
        masked.marital_happiness = AstrologyDataMaskingService.mask_text(tezhi.marital_happiness, preview_length=25)

        return masked

    @staticmethod
    def mask_zhiyin(zhiyin: ZhiyinInfoView) -> ZhiyinInfoView:
        """对真爱指引进行脱敏"""
        masked = zhiyin.model_copy()

        masked.love_location = AstrologyDataMaskingService.mask_text(zhiyin.love_location, preview_length=20)
        masked.meeting_method = AstrologyDataMaskingService.mask_text(zhiyin.meeting_method, preview_length=20)
        masked.interaction_model = AstrologyDataMaskingService.mask_text(zhiyin.interaction_model, preview_length=20)
        masked.love_advice = AstrologyDataMaskingService.mask_text(zhiyin.love_advice, preview_length=30)

        return masked

    @staticmethod
    def mask_zhengyuan_response(response: ApiZhengyuanResponseView) -> ApiZhengyuanResponseView:
        """对正缘画像响应进行脱敏"""
        if not response.data or not response.data.zhengyuan_info:
            return response

        masked_response = response.model_copy(deep=True)
        zhengyuan_details = masked_response.data.zhengyuan_info.zhengyuan_info

        # 脱敏各个部分
        zhengyuan_details.huaxiang = AstrologyDataMaskingService.mask_huaxiang(zhengyuan_details.huaxiang)
        zhengyuan_details.tezhi = AstrologyDataMaskingService.mask_tezhi(zhengyuan_details.tezhi)
        zhengyuan_details.zhiyin = AstrologyDataMaskingService.mask_zhiyin(zhengyuan_details.zhiyin)
        zhengyuan_details.yunshi = AstrologyDataMaskingService.mask_text(zhengyuan_details.yunshi, preview_length=40)

        return masked_response

    @classmethod
    def mask_astrology_response(
            cls,
            response: AstrologyApiResponseView,
            mask_liudao: bool = True,
            mask_zhengyuan: bool = True,
    ) -> AstrologyApiResponseView:
        """
        对占卜API响应进行脱敏处理

        Args:
            response: 原始响应
            mask_liudao: 是否脱敏六道轮回
            mask_zhengyuan: 是否脱敏正缘画像

        Returns:
            脱敏后的响应
        """
        # 深拷贝以避免修改原始数据
        masked_response = response.model_copy(deep=True)

        # 根据配置脱敏不同部分
        if mask_liudao and masked_response.astrology_results.liudao:
            masked_response.astrology_results.liudao = cls.mask_liudao_response(
                masked_response.astrology_results.liudao
            )

        if mask_zhengyuan and masked_response.astrology_results.zhengyuan:
            masked_response.astrology_results.zhengyuan = cls.mask_zhengyuan_response(
                masked_response.astrology_results.zhengyuan
            )

        # 如果有chinese字段，同样处理
        if hasattr(masked_response, 'chinese') and masked_response.chinese:
            if mask_liudao and masked_response.chinese.liudao:
                masked_response.chinese.liudao = cls.mask_liudao_response(
                    masked_response.chinese.liudao
                )

            if mask_zhengyuan and masked_response.chinese.zhengyuan:
                masked_response.chinese.zhengyuan = cls.mask_zhengyuan_response(
                    masked_response.chinese.zhengyuan
                )

        return masked_response