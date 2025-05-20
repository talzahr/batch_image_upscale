import os
import shutil
import argparse
from pathlib import Path
from PIL import Image # Ensure Pillow (or Pillow-SIMD) is installed
import numpy as np
import torch
# Assuming imports from realesrgan and basicsr are correct after basicsr-fixed
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

# --- Configuration ---
MODEL_PHOTO_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth'
MODEL_ANIME_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth'

MODEL_PHOTO_NAME_FOR_SUFFIX = 'RealESRGAN_x4plus'
MODEL_ANIME_NAME_FOR_SUFFIX = 'RealESRGAN_x4plus_anime_6B'
SUFFIX_PHOTO = f'-{MODEL_PHOTO_NAME_FOR_SUFFIX}'
SUFFIX_ANIME = f'-{MODEL_ANIME_NAME_FOR_SUFFIX}'

MODEL_NATIVE_SCALE = 4

SUPPORTED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'] # not setup for animated GIFs

def create_upsampler(model_url, model_name_for_log_and_device, model_inherent_scale, num_blocks):
    """Initializes and returns a RealESRGANer instance."""
    if torch.cuda.is_available():
        device = torch.device('cuda')
        half_precision = True
        print(f"Using GPU for {model_name_for_log_and_device}.")
    else:
        device = torch.device('cpu')
        half_precision = False
        print(f"Warning: Using CPU for {model_name_for_log_and_device}, this will be very slow.")

    model_arch = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64,
        num_block=num_blocks,
        num_grow_ch=32, scale=model_inherent_scale
    )

    print(f"Attempting to initialize RealESRGANer with model_url: '{model_url}' (num_blocks: {num_blocks}, model_scale: {model_inherent_scale})")
    try:
        upsampler = RealESRGANer(
            scale=model_inherent_scale,
            model_path=model_url,
            dni_weight=None,
            model=model_arch,
            tile=0,
            tile_pad=10,
            pre_pad=0,
            half=half_precision,
        )
        print(f"RealESRGANer initialized successfully for {model_name_for_log_and_device}.")
        return upsampler
    except Exception as e:
        print(f"Unexpected error during RealESRGANer init for {model_name_for_log_and_device} using URL {model_url}: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()
        raise

def process_images_in_directory(input_dir_path, output_dir_path, upsampler, model_native_scale, filename_suffix, target_output_scale_factor):
    """Processes all images in a given directory."""
    processed_files = []
    if not input_dir_path.exists() or not input_dir_path.is_dir():
        print(f"Input directory {input_dir_path} does not exist or is not a directory. Skipping.")
        return processed_files

    output_dir_path.mkdir(parents=True, exist_ok=True)
    print(f"\nProcessing images in: {input_dir_path}")
    print(f"Outputting to: {output_dir_path} with target upscale x{target_output_scale_factor} (AI at x{model_native_scale})")

    image_files = [f for f in input_dir_path.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not image_files:
        print("No supported images found.")
        return processed_files

    for img_path in image_files:
        print(f"  Processing: {img_path.name}...")
        try:
            img_pil = Image.open(img_path).convert("RGB")
            img_np = np.array(img_pil)

            # Step 1: Always AI upscale to the model's native scale (e.g., 4x)
            # The 'outscale' here should be the model's native scale
            ai_upscaled_img_np, _ = upsampler.enhance(img_np, outscale=model_native_scale)
            ai_upscaled_img_pil = Image.fromarray(ai_upscaled_img_np)

            # Step 2: If target_output_scale_factor is different from model_native_scale,
            #         manually resize using Pillow with Lanczos.
            final_img_pil = ai_upscaled_img_pil
            if target_output_scale_factor != model_native_scale:
                original_width, original_height = img_pil.size
                target_width = int(original_width * target_output_scale_factor)
                target_height = int(original_height * target_output_scale_factor)
                
                print(f"    Resizing from AI x{model_native_scale} ({ai_upscaled_img_pil.width}x{ai_upscaled_img_pil.height}) to target x{target_output_scale_factor} ({target_width}x{target_height}) using Lanczos...")
                final_img_pil = ai_upscaled_img_pil.resize((target_width, target_height), Image.Resampling.LANCZOS)

            base_name = img_path.stem
            if target_output_scale_factor == int(target_output_scale_factor):
                scale_str = f"{int(target_output_scale_factor)}x"
            else:
                scale_str = f"{target_output_scale_factor:.1f}x".replace(".0x","x")

            output_filename = f"{base_name}{filename_suffix}-out{scale_str}.png"
            output_save_path = output_dir_path / output_filename
            final_img_pil.save(output_save_path, quality=95) # Adjust quality for PNG if needed (lossless by default)
            print(f"  Saved: {output_save_path}")
            processed_files.append(img_path)
        except Exception as e:
            print(f"  Error processing {img_path.name}: {e}")
            import traceback
            traceback.print_exc()
    
    return processed_files

def main():
    parser = argparse.ArgumentParser(description="Upscale images using Real-ESRGAN and Pillow-Lanczos for final scaling.")
    parser.add_argument(
        "-o", "--output-path",
        type=str,
        default=None,
        help="Base path for output directories."
    )
    parser.add_argument(
        "-u", "--upscale",
        type=float,
        default=4.0,
        help=f"Target upscale factor for the output image (e.g., 2.0 for 2x). AI upscale is always x{MODEL_NATIVE_SCALE}. Default: 4.0"
    )
    args = parser.parse_args()

    if args.upscale <= 0:
        print("Error: Upscale factor must be positive.")
        return
    
    target_output_scale = args.upscale

    script_dir = Path(__file__).resolve().parent
    input_photo_dir = script_dir / "input_photo"
    input_anime_dir = script_dir / "input_anime"

    if args.output_path:
        output_base_dir = Path(args.output_path).resolve()
        output_photo_dir = output_base_dir / "output_photo"
        output_anime_dir = output_base_dir / "output_anime"
    else:
        output_photo_dir = script_dir / "output_photo"
        output_anime_dir = script_dir / "output_anime"

    output_photo_dir.parent.mkdir(parents=True, exist_ok=True)
    output_anime_dir.parent.mkdir(parents=True, exist_ok=True)

    print("Initializing upscalers...")
    try:
        photo_upsampler = create_upsampler(MODEL_PHOTO_URL, MODEL_PHOTO_NAME_FOR_SUFFIX, MODEL_NATIVE_SCALE, num_blocks=23)
        anime_upsampler = create_upsampler(MODEL_ANIME_URL, MODEL_ANIME_NAME_FOR_SUFFIX, MODEL_NATIVE_SCALE, num_blocks=6)
    except Exception as e:
        print(f"Fatal error initializing upscalers: {e}")
        return

    all_processed_input_files = []

    if input_photo_dir.exists():
        # Pass MODEL_NATIVE_SCALE to process_images_in_directory
        processed_photo_files = process_images_in_directory(
            input_photo_dir, output_photo_dir, photo_upsampler, 
            MODEL_NATIVE_SCALE, SUFFIX_PHOTO, target_output_scale
        )
        all_processed_input_files.extend(processed_photo_files)
    else:
        print(f"Input photo directory not found: {input_photo_dir}")

    if input_anime_dir.exists():
        processed_anime_files = process_images_in_directory(
            input_anime_dir, output_anime_dir, anime_upsampler, 
            MODEL_NATIVE_SCALE, SUFFIX_ANIME, target_output_scale
        )
        all_processed_input_files.extend(processed_anime_files)
    else:
        print(f"Input anime directory not found: {input_anime_dir}")

    print("\nUpscaling complete.")

    # ... (rest of input deletion logic remains the same) ...
    if all_processed_input_files:
        while True:
            choice = input("Would you like to retain the images in INPUT DIRs? [Y/n]: ").strip().lower()
            if choice == 'y' or choice == '':
                print("Retaining input images.")
                break
            elif choice == 'n':
                print("Deleting processed input images...")
                for file_path in all_processed_input_files:
                    try:
                        file_path.unlink()
                        print(f"  Deleted: {file_path}")
                    except Exception as e:
                        print(f"  Error deleting {file_path}: {e}")
                print("Input images deleted.")
                break
            else:
                print("Invalid choice. Please enter 'Y' or 'n'.")
    else:
        print("No images were processed, so no input files to potentially delete.")

if __name__ == "__main__":
    main()