#!/usr/bin/env python3
"""
로또 6/45 통합 테스트 - UnboundLocalError 방지 검증
Mock을 사용하여 success 변수 관련 오류가 발생하지 않는지 확인
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.chdir(os.path.join(os.path.dirname(__file__), '..', 'src'))


@patch('time.sleep')  # 테스트 속도 향상
@patch('lotto645.notify_lotto645_purchase')
def test_no_unbound_local_error_on_early_exception(mock_notify, mock_sleep):
    """
    구매 초기에 예외 발생 시에도 success 변수 참조로 인한
    UnboundLocalError가 발생하지 않는지 검증
    """
    from datetime import datetime, timezone, timedelta
    from lotto645 import purchase_lotto645
    
    mock_page = MagicMock()
    # page.goto에서 예외 발생 시뮬레이션 (3번 재시도 후 raise)
    mock_page.goto.side_effect = Exception("네트워크 오류")
    
    with pytest.raises(Exception) as exc_info:
        purchase_lotto645(mock_page, auto_games=5, manual_numbers=[], use_mobile=False)
    
    # UnboundLocalError가 아닌 원래 예외가 발생해야 함
    assert "referenced before assignment" not in str(exc_info.value)
    # notify는 예외 메시지와 함께 호출되어야 함
    mock_notify.assert_called()
    call_args = mock_notify.call_args
    assert call_args[0][2] is False  # success=False
    kwargs = call_args[1] if len(call_args) > 1 else {}
    assert "네트워크 오류" in str(kwargs.get('error_msg', ''))
