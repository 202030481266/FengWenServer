from datetime import datetime

from zhdate import ZhDate


def gregorian_to_lunar(birth_date: datetime) -> str:
    """Convert gregorian date to lunar date"""
    try:
        lunar = ZhDate.from_datetime(birth_date)
        return f"{lunar.lunar_year}-{lunar.lunar_month:02d}-{lunar.lunar_day:02d}"
    except Exception as e:
        return f"Error converting date: {str(e)}"

def get_lunar_info(birth_date: datetime) -> dict:
    """Get detailed lunar calendar information"""
    try:
        lunar = ZhDate.from_datetime(birth_date)
        return {
            "lunar_date": f"{lunar.lunar_year}-{lunar.lunar_month:02d}-{lunar.lunar_day:02d}",
            "lunar_year": lunar.lunar_year,
            "lunar_month": lunar.lunar_month,
            "lunar_day": lunar.lunar_day,
            "is_leap_month": lunar.is_leap,
            "chinese_era": lunar.chinese()
        }
    except Exception as e:
        return {"error": str(e)}