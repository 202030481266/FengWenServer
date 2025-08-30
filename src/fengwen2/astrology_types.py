from typing import List

from pydantic import BaseModel


class ZhenInfo(BaseModel):
    """真太阳时信息"""
    province: str
    city: str
    jingdu: str
    weidu: str
    shicha: str

class BaseInfo(BaseModel):
    """基本信息"""
    zhen: ZhenInfo | None = None
    sex: str
    name: str
    gongli: str
    nongli: str
    qiyun: str
    jiaoyun: str
    zhengge: str | None = None
    wuxing_xiji: str | None = None

class XiyongshenInfo(BaseModel):
    """喜用神信息"""
    qiangruo: str
    xiyongshen: str
    jishen: str
    xiyongshen_desc: str
    jin_number: int
    mu_number: int
    shui_number: int
    huo_number: int
    tu_number: int
    tonglei: str
    yilei: str
    rizhu_tiangan: str
    zidang: float  # zidang and yidang could be float or int
    yidang: float
    zidang_percent: str
    yidang_percent: str
    jin_score: float
    mu_score: float
    shui_score: float
    huo_score: float
    tu_score: float
    jin_score_percent: str
    mu_score_percent: str
    shui_score_percent: str
    huo_score_percent: str
    tu_score_percent: str
    yinyang: str
    wuxingxiji: str | None = None

# --- 八字测算 (Bazi Calculation) ---

class BaziInfo(BaseModel):
    """八字信息"""
    kw: str
    tg_cg_god: List[str]
    bazi: str
    na_yin: str

class ChengguInfo(BaseModel):
    """称骨信息"""
    year_weight: str
    month_weight: str
    day_weight: str
    hour_weight: str
    total_weight: str
    description: str

class WuxingInfo(BaseModel):
    """五行信息"""
    detail_desc: str
    simple_desc: str
    simple_description: str
    detail_description: str

class YinyuanInfo(BaseModel):
    """姻缘信息"""
    sanshishu_yinyuan: str

class SanshishuCaiyun(BaseModel):
    """三世书财运"""
    simple_desc: str
    detail_desc: str

class CaiyunInfo(BaseModel):
    """财运信息"""
    sanshishu_caiyun: SanshishuCaiyun

class SizhuInfo(BaseModel):
    """四柱信息"""
    rizhu: str

class MingyunInfo(BaseModel):
    """命运信息"""
    sanshishu_mingyun: str

class CesuanResult(BaseModel):
    """八字测算结果"""
    base_info: BaseInfo
    bazi_info: BaziInfo
    chenggu: ChengguInfo
    wuxing: WuxingInfo
    yinyuan: YinyuanInfo
    caiyun: CaiyunInfo
    sizhu: SizhuInfo
    mingyun: MingyunInfo
    sx: str
    xz: str
    xiyongshen: XiyongshenInfo

# --- 六道轮回 (Liudao Reincarnation) ---

class LiudaoInfoItem(BaseModel):
    """六道信息项"""
    liudao_name: str
    liudao_simple_desc: str
    liudao_detail_desc: str

class Minggua(BaseModel):
    """命卦"""
    minggua_name: str
    minggua_fangwei: str

class ExtendedBaseInfo(BaseInfo):
    """
    用于'六道轮回'和'正缘画像'的扩展基本信息
    """
    taiyuan: str | None = None
    taiyuan_nayin: str | None = None
    taixi: str | None = None
    taixi_nayin: str | None = None
    minggong: str | None = None
    minggong_nayin: str | None = None
    shengong: str | None = None
    shengong_nayin: str | None = None
    shengxiao: str | None = None
    xingzuo: str | None = None
    siling: str | None = None
    jiaoyun_mang: str | None = None
    xingxiu: str | None = None
    minggua: Minggua | None = None
    wuxing_wangdu: str | None = None
    tiangan_liuyi: str | None = None
    dizhi_liuyi: str | None = None
    xiyongshen: XiyongshenInfo | None = None

class LiudaoDetails(BaseModel):
    """六道详细信息"""
    past_info: LiudaoInfoItem
    now_info: LiudaoInfoItem
    future_info: LiudaoInfoItem

class LiudaoInfo(BaseModel):
    """六道信息"""
    base_info: ExtendedBaseInfo
    liudao_info: LiudaoDetails

# --- 正缘画像 (Zhengyuan Portrait) ---

class HuaxiangInfo(BaseModel):
    """真爱画像"""
    face_shape: str
    eyebrow_shape: str
    eye_shape: str
    mouth_shape: str
    nose_shape: str
    body_shape: str
    profile_image: str | None = None

class TezhiInfo(BaseModel):
    """真爱特质"""
    romantic_personality: str
    family_background: str
    career_wealth: str
    marital_happiness: str

class ZhiyinInfo(BaseModel):
    """真爱指引"""
    love_location: str
    meeting_method: str
    interaction_model: str
    love_advice: str

class ZhengyuanDetails(BaseModel):
    """正缘详细信息"""
    huaxiang: HuaxiangInfo
    tezhi: TezhiInfo
    zhiyin: ZhiyinInfo
    yunshi: str

class ZhengyuanInfo(BaseModel):
    """正缘信息"""
    base_info: ExtendedBaseInfo
    zhengyuan_info: ZhengyuanDetails


# --- 封装模型 (Top-level Wrapper Models) ---

class ApiBaziResponse(BaseModel):
    """八字API响应数据"""
    errcode: int | None = None
    errmsg: str | None = None
    success: bool | None = None
    data: CesuanResult

class ApiLiudaoResponse(BaseModel):
    """六道API响应数据"""
    errcode: int | None = None
    errmsg: str | None = None
    success: bool | None = None
    data: LiudaoInfo

class ApiZhengyuanResponse(BaseModel):
    """正缘API响应数据"""
    errcode: int | None = None
    errmsg: str | None = None
    success: bool | None = None
    data: ZhengyuanInfo

class AstrologyResults(BaseModel):
    """合并测算结果（包含中英文）"""
    bazi: ApiBaziResponse
    liudao: ApiLiudaoResponse
    zhengyuan: ApiZhengyuanResponse

class LunarInfo(BaseModel):
    """日历中的农历信息"""
    year: int
    month: int
    day: int
    formatted: str

class CalendarInfo(BaseModel):
    """日历信息"""
    success: bool
    birth_datetime: str
    solar_date: str
    birth_time: str
    lunar_info: LunarInfo

class AstrologyApiResponse(BaseModel):
    """最终的、完整的API响应模型"""
    astrology_results: AstrologyResults
    chinese: AstrologyResults
    shopify_url: str