#!/usr/bin/env python3
"""
로또 6/45 구매 모듈 테스트
- success 변수 초기화 검증
- notify 호출 시 파라미터 검증
- 번호 추출 로직 검증
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# src 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
os.chdir(os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestLotto645SuccessVariable:
    """success 변수가 모든 경로에서 정의되는지 검증"""

    def test_success_initialized_at_start(self):
        """success 변수가 함수 시작 시 반드시 초기화되는지 확인"""
        import inspect
        from lotto645 import purchase_lotto645
        
        source = inspect.getsource(purchase_lotto645)
        # success, final_numbers 반드시 초기화
        assert 'success = False' in source
        assert 'final_numbers = []' in source


class TestNotifyLotto645:
    """notify_lotto645_purchase 호출 검증"""

    def test_notify_success_with_numbers(self):
        """성공 시 번호가 포함된 메시지 생성"""
        from telegram_notifier import notify_lotto645_purchase
        # 실제 전송 대신 메시지 생성 로직만 검증
        with patch('telegram_notifier.send_telegram_message') as mock_send:
            notify_lotto645_purchase(3, 2, True, numbers=[[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]])
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            assert "구매 완료" in msg
            assert "구매 번호" in msg
            # 번호는 02d 포맷으로 표시됨
            assert "01" in msg and "06" in msg

    def test_notify_failure_with_error(self):
        """실패 시 오류 메시지 포함"""
        from telegram_notifier import notify_lotto645_purchase
        with patch('telegram_notifier.send_telegram_message') as mock_send:
            notify_lotto645_purchase(5, 0, False, error_msg="테스트 오류")
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            assert "구매 실패" in msg
            assert "테스트 오류" in msg


class TestParseArguments:
    """parse_arguments 함수 검증"""

    def test_parse_auto_amount(self):
        """자동 구매 금액 파싱"""
        from lotto645 import parse_arguments
        with patch.dict(os.environ, {'AUTO_GAMES': '0', 'MANUAL_NUMBERS': '[]'}):
            with patch.object(sys, 'argv', ['lotto645.py', '5000']):
                auto, manual = parse_arguments()
                assert auto == 5
                assert manual == []

    def test_parse_manual_numbers(self):
        """수동 번호 파싱"""
        from lotto645 import parse_arguments
        with patch.object(sys, 'argv', ['lotto645.py', '1', '2', '3', '4', '5', '6']):
            auto, manual = parse_arguments()
            assert auto == 0
            assert manual == [[1, 2, 3, 4, 5, 6]]


class TestNumberExtraction:
    """번호 추출 로직 검증"""

    def test_valid_lotto_numbers(self):
        """유효한 로또 번호 검증 (1-45, 6개, 중복 없음)"""
        def is_valid_numbers(nums):
            return (len(nums) == 6 and 
                    all(1 <= n <= 45 for n in nums) and 
                    len(set(nums)) == 6)
        
        assert is_valid_numbers([1, 2, 3, 4, 5, 6])
        assert is_valid_numbers([7, 14, 21, 28, 35, 42])
        assert not is_valid_numbers([1, 2, 3, 4, 5])  # 5개
        assert not is_valid_numbers([1, 2, 3, 4, 5, 50])  # 50 불가
        assert not is_valid_numbers([1, 2, 3, 4, 5, 5])  # 중복
