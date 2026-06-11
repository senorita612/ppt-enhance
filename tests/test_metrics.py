import numpy as np

from ppt_enhance.eval.metrics import compute_cer, compute_ssim_psnr


def test_ssim_identical():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    ssim, psnr = compute_ssim_psnr(img, img)
    assert ssim == 1.0
    assert psnr == float("inf")


def test_cer():
    assert compute_cer("深度学习", "深度学习") == 0.0
    assert compute_cer("学习", "学刁") > 0
