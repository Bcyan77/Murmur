"""오디오 세션 열거 테스트.

현재 시스템에서 오디오를 출력 중인 프로세스 목록을 출력한다.
브라우저, 음악 플레이어, 게임 등이 소리를 내는 동안 실행해보면 확인 가능.
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from murmur.audio.sessions import list_audio_sessions


def main() -> None:
    sessions = list_audio_sessions()
    if not sessions:
        print("오디오 세션이 없습니다. (오디오 출력 중인 앱 없음 또는 Windows가 아님)")
        return

    print(f"감지된 오디오 세션: {len(sessions)}개")
    print("-" * 60)
    for s in sessions:
        print(f"  PID {s.pid:>6}  {s.name:<30}  {s.display_name}")


if __name__ == "__main__":
    main()
