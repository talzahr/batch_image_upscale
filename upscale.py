import os
import shutil
import argparse
from pathlib import Path
from PIL import Image
import numpy as np
import torch
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet # Required by RealESRGANer

# Configuration
MODEL_PHOTO_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth'
MODEL_ANIME_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth'

MODEL_PHOTO_NAME = 'RealESRGAN_x4plus'
MODEL_ANIME_NAME = 'RealESRGAN_x4plus_anime_6B'

MODEL_PHOTO_NAME_FOR_SUFFIX = 'RealESRGAN_x4plus' # Used for filename suffix
MODEL_ANIME_NAME_FOR_SUFFIX = 'RealESRGAN_x4plus_anime_6B' # Used for filename suffix
SUFFIX_PHOTO = f'-{MODEL_PHOTO_NAME_FOR_SUFFIX}'
SUFFIX_ANIME = f'-{MODEL_ANIME_NAME_FOR_SUFFIX}'

# Scale
UPSCALE_FACTOR = 4

# Supported image extensions
SUPPORTED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']

# Add num_block to the function signature
def create_upsampler(model_url, model_name_for_log_and_device, scale_factor, num_blocks):
    """Initializes and returns a RealESRGANer instance."""
    if torch.cuda.is_available():
        device = torch.device('cuda')
        half_precision = True
        print(f"Using GPU for {model_name_for_log_and_device}.")
    else:
        device = torch.device('cpu')
        half_precision = False
        print(f"Warning: Using CPU for {model_name_for_log_and_device}, this will be very slow.")

    # Use the passed num_blocks parameter here
    model_arch = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64, 
        num_block=num_blocks,  # Use the parameter
        num_grow_ch=32, scale=scale_factor
    )

    print(f"Attempting to initialize RealESRGANer with model_url: '{model_url}' (num_blocks: {num_blocks})")
    try:
        upsampler = RealESRGANer(
            scale=scale_factor,
            model_path=model_url,
            dni_weight=None,
            model=model_arch, # Pass the correctly configured model_arch
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

def process_images_in_directory(input_dir_path, output_dir_path, upsampler, filename_suffix):
    """Processes all images in a given directory."""
    processed_files = []
    if not input_dir_path.exists() or not input_dir_path.is_dir():
        print(f"Input directory {input_dir_path} does not exist or is not a directory. Skipping.")
        return processed_files

    output_dir_path.mkdir(parents=True, exist_ok=True)
    print(f"\nProcessing images in: {input_dir_path}")
    print(f"Outputting to: {output_dir_path}")

    image_files = [f for f in input_dir_path.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not image_files:
        print("No supported images found.")
        return processed_files

    for img_path in image_files:
        print(f"  Processing: {img_path.name}...")
        try:
            img = Image.open(img_path).convert("RGB")
            img_np = np.array(img)

            output_img_np, _ = upsampler.enhance(img_np, outscale=UPSCALE_FACTOR)

            output_img = Image.fromarray(output_img_np)
            
            base_name = img_path.stem
            extension = img_path.suffix # Keep original extension, or force .png
            # Forcing PNG for consistent output quality, but can keep original:
            # output_filename = f"{base_name}{filename_suffix}{extension}"
            output_filename = f"{base_name}{filename_suffix}.png" # Force PNG

            output_save_path = output_dir_path / output_filename
            output_img.save(output_save_path)
            print(f"  Saved: {output_save_path}")
            processed_files.append(img_path)
        except Exception as e:
            print(f"  Error processing {img_path.name}: {e}")
    
    return processed_files


def main():
    parser = argparse.ArgumentParser(description="Upscale images using Real-ESRGAN.")
    parser.add_argument(
        "-o", "--output-path",
        type=str,
        default=None,
        help="Base path for output directories. If not set, 'output_photo' and 'output_anime' will be created in the script's directory."
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent

    # Define input directories relative to the script
    input_photo_dir = script_dir / "input_photo"
    input_anime_dir = script_dir / "input_anime"

    # Define output directories
    if args.output_path:
        output_base_dir = Path(args.output_path).resolve()
        output_photo_dir = output_base_dir / "output_photo"
        output_anime_dir = output_base_dir / "output_anime"
    else:
        output_photo_dir = script_dir / "output_photo"
        output_anime_dir = script_dir / "output_anime"

    # Create base output directories if they don't exist
    output_photo_dir.parent.mkdir(parents=True, exist_ok=True)
    output_anime_dir.parent.mkdir(parents=True, exist_ok=True)


    print("Initializing upscalers...")
    try:
        # Standard photo model uses num_block=23
        photo_upsampler = create_upsampler(MODEL_PHOTO_URL, MODEL_PHOTO_NAME_FOR_SUFFIX, UPSCALE_FACTOR, num_blocks=23)
        
        # Anime_6B model uses num_block=6
        anime_upsampler = create_upsampler(MODEL_ANIME_URL, MODEL_ANIME_NAME_FOR_SUFFIX, UPSCALE_FACTOR, num_blocks=6)
    
    except Exception as e:
        # This general exception catch might be the one you saw first:
        # "Error initializing upscalers: create_upsampler() missing 1 required positional argument: 'scale_factor'"
        # This was likely because the anime_upsampler failed, and the error propagated up.
        # We should make this more specific if needed, or just let the create_upsampler re-raise.
        print(f"Error initializing upscalers: {e}")
        print("Please ensure Real-ESRGAN is installed correctly and model files are accessible.")
        print("You might need to run the script once to allow models to download, or place them in a 'weights' folder.")
        return # Exit if upscalers can't be initialized

    all_processed_input_files = []

    # Process Photo images
    if input_photo_dir.exists():
        processed_photo_files = process_images_in_directory(input_photo_dir, output_photo_dir, photo_upsampler, SUFFIX_PHOTO)
        all_processed_input_files.extend(processed_photo_files)
    else:
        print(f"Input photo directory not found: {input_photo_dir}")

    # Process Anime images
    if input_anime_dir.exists():
        processed_anime_files = process_images_in_directory(input_anime_dir, output_anime_dir, anime_upsampler, SUFFIX_ANIME)
        all_processed_input_files.extend(processed_anime_files)
    else:
        print(f"Input anime directory not found: {input_anime_dir}")

    print("\nUpscaling complete.")

    # Ask to retain input images
    if all_processed_input_files:
        while True:
            choice = input("Would you like to retain the images in INPUT DIRs? [Y/n]: ").strip().lower()
            if choice == 'y' or choice == '': # Default to Yes if empty
                print("Retaining input images.")
                break
            elif choice == 'n':
                print("Deleting processed input images...")
                for file_path in all_processed_input_files:
                    try:
                        file_path.unlink() # Deletes the file
                        print(f"  Deleted: {file_path}")
                    except Exception as e:
                        print(f"  Error deleting {file_path}: {e}")
                # You could also delete the input directories if they are now empty
                # For example, if not os.listdir(input_photo_dir): shutil.rmtree(input_photo_dir)
                print("Input images deleted.")
                break
            else:
                print("Invalid choice. Please enter 'Y' or 'n'.")
    else:
        print("No images were processed, so no input files to potentially delete.")

if __name__ == "__main__":
    # Ensure model weights directory exists if realesrgan expects it for downloads
    # This is often handled internally by realesrgan if it downloads,
    # but creating it doesn't hurt if you plan to manually place models.
    weights_dir = Path(__file__).resolve().parent / "weights"
    weights_dir.mkdir(exist_ok=True)
    
    main()