from typing import Any

from pydantic import ValidationError


def debug_validation_error(validation_error: ValidationError, raw_data: Any = None):
    """通用的 ValidationError 调试函数"""

    print("\n" + "=" * 60)
    print("VALIDATION ERROR DETAILS")
    print("=" * 60)

    # 1. 错误摘要
    print(f"\n📊 Error Summary:")
    print(f"   Total errors: {validation_error.error_count()}")

    # 2. 详细错误列表
    print(f"\n📋 Detailed Errors:")
    for idx, error in enumerate(validation_error.errors(), 1):
        print(f"\n   Error #{idx}:")
        print(f"   • Location: {' -> '.join(map(str, error['loc']))}")
        print(f"   • Type: {error['type']}")
        print(f"   • Message: {error['msg']}")
        if 'input' in error:
            input_str = str(error['input'])
            if len(input_str) > 100:
                input_str = input_str[:100] + "..."
            print(f"   • Input: {input_str}")
        if error.get('ctx'):
            print(f"   • Context: {error['ctx']}")

    # 3. 如果提供了原始数据，显示数据结构
    if raw_data:
        print(f"\n📁 Data Structure:")

        def show_structure(obj, indent=0):
            prefix = "   " + "  " * indent
            if isinstance(obj, dict):
                print(f"{prefix}dict ({len(obj)} keys)")
                for key in list(obj.keys())[:5]:  # 只显示前5个键
                    print(f"{prefix}  • {key}: {type(obj[key]).__name__}")
            elif isinstance(obj, list):
                print(f"{prefix}list ({len(obj)} items)")
                if obj:
                    print(f"{prefix}  • [0]: {type(obj[0]).__name__}")
            else:
                print(f"{prefix}{type(obj).__name__}")

        show_structure(raw_data)

    print("\n" + "=" * 60 + "\n")
