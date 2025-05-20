# Batch Image Upscale

##(CLI: upscale.py)

Just something I made for myself for fun and upscale some old images.

Uses Real-ESRGAN w/ x4plus and x4plus_anime_6B models to AI upscale images from `./import_photo` and `./import_anime` directories using their respective model. The output files go to `./output_photo` and `./output_anime`

`-o`, `--output-path` option for a custom output location.

`-u`, `--upscale` option to resample at the desired multiplier. i.e. `-u 2.0` or `-u 2` for 2x size. This uses Pillow's Lanczos resampling as RealESRGAN models do 4x upscaling natively and its built-in resampling uses bicubic.

## Tkinter interface: gui.py

- Wrapper for upscale.py;
- Drag and drop images to the input panel;
- Tabs for *Photos* and *Illustrations*;
- Defaults to our preset directories/folders set in upscale.py;
- Right-click context menus;
- Double click to open image in your OS user default image viewer;

Simple implementation for now until I add more features to upscale.py (as mentioned in the 'To Do')

## Installation

`git clone https://github.com/talzahr/batch_image_upscale.git` to clone this repo.

`cd batch_image_upscale`

`pip install -r requirements-cuda.txt` for CUDA supported Torch, Torchvision and Torchaudio. Uses CUDA 12.1 by default, but can modify it for a later or earlier version such as `cu118`

**OR**

`pip install -r requirements-cpu.txt` for the typical Torch CPU builds.

## NCNN Vulkan not yet supported

At the moment this does not utilize the [NCNN-Vulkan implementation of Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) but should be fairly easy to implement.

# To Do

1. *Bending feature*: take original image and upsample it with bicubic/Lanczos and blend it into upscaled image for a more realistic look.
2. *Bring in realesr-general-x4v3 model*: May work better with photos.
~~3. *GUI*?: Why not. ~~
