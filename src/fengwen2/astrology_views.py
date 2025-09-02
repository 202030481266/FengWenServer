from pydantic import BaseModel


# --- Bazi (八字测算) Section View Models ---

class BaseInfoView(BaseModel):
    """基本信息视图模型"""
    name: str
    gongli: str
    nongli: str
    zhengge: str | None = None


class BaziInfoView(BaseModel):
    """八字信息视图模型"""
    na_yin: str
    bazi: str


class XiyongshenInfoView(BaseModel):
    """喜用神信息视图模型"""
    qiangruo: str
    xiyongshen: str
    jishen: str
    xiyongshen_desc: str
    tonglei: str
    yilei: str
    rizhu_tiangan: str
    jin_score: float
    mu_score: float
    shui_score: float
    huo_score: float
    tu_score: float


class WuxingInfoView(BaseModel):
    """五行信息视图模型"""
    detail_description: str


class YinyuanInfoView(BaseModel):
    """姻缘信息视图模型"""
    sanshishu_yinyuan: str


class SanshishuCaiyunView(BaseModel):
    """三世书财运视图模型"""
    detail_desc: str


class CaiyunInfoView(BaseModel):
    """财运信息视图模型"""
    sanshishu_caiyun: SanshishuCaiyunView


class CesuanResultView(BaseModel):
    """八字测算核心结果视图模型"""
    base_info: BaseInfoView
    bazi_info: BaziInfoView
    wuxing: WuxingInfoView
    yinyuan: YinyuanInfoView
    caiyun: CaiyunInfoView
    sx: str
    xz: str
    xiyongshen: XiyongshenInfoView


# --- Liudao (六道轮回) Section View Models ---

class LiudaoInfoItemView(BaseModel):
    """六道信息项视图模型 (包含完整描述)"""
    liudao_name: str
    liudao_simple_desc: str
    liudao_detail_desc: str


class LiudaoDetailsView(BaseModel):
    """六道详细信息视图模型"""
    past_info: LiudaoInfoItemView
    now_info: LiudaoInfoItemView
    future_info: LiudaoInfoItemView


class LiudaoInfoView(BaseModel):
    """六道信息核心结果视图模型"""
    liudao_info: LiudaoDetailsView


# --- Zhengyuan (正缘画像) Section View Models ---

class HuaxiangInfoView(BaseModel):
    """真爱画像视图模型 (包含所有面部特征)"""
    face_shape: str
    eyebrow_shape: str
    eye_shape: str
    mouth_shape: str
    nose_shape: str
    body_shape: str


class TezhiInfoView(BaseModel):
    """真爱特质视图模型"""
    romantic_personality: str
    family_background: str
    career_wealth: str
    marital_happiness: str


class ZhiyinInfoView(BaseModel):
    """真爱指引视图模型"""
    love_location: str
    meeting_method: str
    interaction_model: str
    love_advice: str


class ZhengyuanDetailsView(BaseModel):
    """正缘详细信息视图模型"""
    huaxiang: HuaxiangInfoView
    tezhi: TezhiInfoView
    zhiyin: ZhiyinInfoView
    yunshi: str


class ZhengyuanInfoView(BaseModel):
    """正缘信息核心结果视图模型"""
    zhengyuan_info: ZhengyuanDetailsView


# --- Top-level Wrapper View Models ---

class ApiBaziResponseView(BaseModel):
    """八字API响应视图模型"""
    errcode: int | None = None
    errmsg: str | None = None
    data: CesuanResultView


class ApiLiudaoResponseView(BaseModel):
    """六道API响应视图模型"""
    errcode: int | None = None
    errmsg: str | None = None
    data: LiudaoInfoView


class ApiZhengyuanResponseView(BaseModel):
    """正缘API响应视图模型"""
    errcode: int | None = None
    errmsg: str | None = None
    data: ZhengyuanInfoView


class AstrologyResultsView(BaseModel):
    """合并测算结果视图模型"""
    bazi: ApiBaziResponseView
    liudao: ApiLiudaoResponseView
    zhengyuan: ApiZhengyuanResponseView


class AstrologyApiResponseView(BaseModel):
    """最终的、完整的API响应视图模型"""
    astrology_results: AstrologyResultsView
    chinese: AstrologyResultsView
    record_id: int
