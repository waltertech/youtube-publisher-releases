"""Stable-ID selection shared by all three channel configuration stages."""
def select_windows(windows, window_ids=None):
    if window_ids is None:
        return windows
    if not isinstance(window_ids, (list, tuple, set)) or not window_ids or any(not isinstance(i,str) or not i for i in window_ids):
        raise ValueError('请至少选择一个有效窗口')
    ids = set(window_ids)
    unknown = ids - {w['id'] for w in windows}
    if unknown:
        raise ValueError('所选窗口已失效，请刷新窗口列表后重新选择')
    return [w for w in windows if w['id'] in ids]
