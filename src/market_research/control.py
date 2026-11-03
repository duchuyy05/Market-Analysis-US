"""Cooperative cancellation shared by the workflow and HTTP providers."""


class RunCancelled(Exception):
    """Stop without treating a user request as a provider or workflow failure."""


def check_cancel(event):
    if event is not None and event.is_set():
        raise RunCancelled("Đã dừng theo yêu cầu; dữ liệu đã nhận và checkpoint được giữ lại")
