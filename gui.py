import customtkinter as ctk
from tkinter import filedialog
from PIL import Image # ImageTk is part of Pillow if Pillow >= 9.1.0, else from PIL import ImageTk
try:
    from PIL import ImageTk # Modern Pillow
except ImportError:
    import ImageTk # Older Pillow

import os
import shutil
import subprocess
import threading
import queue
from tkinterdnd2 import DND_FILES, TkinterDnD # Import for Drag & Drop
import sys # need this for sys.executable for running in a venv

# --- Configuration ---
THUMBNAIL_SIZE = (100, 100)
INPUT_PHOTO_DIR = "input_photo"
INPUT_ANIME_DIR = "input_anime"
OUTPUT_PHOTO_DIR = "output_photo"
OUTPUT_ANIME_DIR = "output_anime"
PYTHON_EXECUTABLE = sys.executable # Should use the venv python if running from venv

ctk.set_appearance_mode("Dark") # System, Dark, Light
ctk.set_default_color_theme("blue") # dark-blue, green, etc

# To make CustomTkinter work with TkinterDnD2, we need to use TkinterDnD.Tk()
# instead of ctk.CTk(). We can then embed CTkFrames within it.
class App(TkinterDnD.Tk): # Changed from ctk.CTk
    def __init__(self):
        super().__init__() # Initialize TkinterDnD.Tk
        self.title("Real-ESRGAN Upscaler GUI")
        self.geometry("1200x750")

        # --- Data ---
        self.photo_input_paths = {} # Stores {display_name: absolute_path} to avoid duplicates and manage originals
        self.anime_input_paths = {} # Stores {display_name: absolute_path}
        self.processing_thread = None
        self.process = None
        self.is_processing = False
        self.output_queue = queue.Queue()

        # --- Ensure directories exist ---
        for dir_path in [INPUT_PHOTO_DIR, INPUT_ANIME_DIR, OUTPUT_PHOTO_DIR, OUTPUT_ANIME_DIR]:
            os.makedirs(dir_path, exist_ok=True)

        # --- Main Layout (using CTkFrame as the main container inside TkinterDnD.Tk) ---
        self.main_frame = ctk.CTkFrame(self) # No explicit fg_color needed here if global theme is set
        self.main_frame.pack(expand=True, fill="both")

        self.main_frame.grid_columnconfigure(0, weight=1) # Input
        self.main_frame.grid_columnconfigure(1, weight=2) # Center
        self.main_frame.grid_columnconfigure(2, weight=1) # Output
        self.main_frame.grid_rowconfigure(0, weight=1)

        # --- Input Pane ---
        self.input_pane = ctk.CTkFrame(self.main_frame)
        self.input_pane.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.input_pane.grid_rowconfigure(0, weight=1)
        self.input_pane.grid_columnconfigure(0, weight=1)

        self.input_tabview = ctk.CTkTabview(self.input_pane)
        self.input_tabview.pack(expand=True, fill="both", padx=5, pady=5)
        self.input_tabview.add("Photos")
        self.input_tabview.add("Illustrations")

        self.input_photos_scrollable_frame = ctk.CTkScrollableFrame(self.input_tabview.tab("Photos"), label_text="Input Photos")
        self.input_photos_scrollable_frame.pack(expand=True, fill="both", padx=5, pady=5)

        self.input_anime_scrollable_frame = ctk.CTkScrollableFrame(self.input_tabview.tab("Illustrations"), label_text="Input Illustrations")
        self.input_anime_scrollable_frame.pack(expand=True, fill="both", padx=5, pady=5)

        # Enable Drag and Drop
        self.input_tabview.tab("Photos").drop_target_register(DND_FILES)
        self.input_tabview.tab("Photos").dnd_bind('<<Drop>>', lambda e: self.handle_drop(e, "Photos"))
        self.input_tabview.tab("Illustrations").drop_target_register(DND_FILES)
        self.input_tabview.tab("Illustrations").dnd_bind('<<Drop>>', lambda e: self.handle_drop(e, "Illustrations"))


        # --- Center Pane ---
        self.center_pane = ctk.CTkFrame(self.main_frame)
        self.center_pane.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.center_pane.grid_rowconfigure(0, weight=0)  # Add files button
        self.center_pane.grid_rowconfigure(1, weight=0)  # Add dir button
        self.center_pane.grid_rowconfigure(2, weight=0)  # Refresh button
        self.center_pane.grid_rowconfigure(3, weight=1)  # Status display
        self.center_pane.grid_rowconfigure(4, weight=0)  # Upscale Label
        self.center_pane.grid_rowconfigure(5, weight=0)  # Upscale slider & value
        self.center_pane.grid_rowconfigure(6, weight=0)  # Start/Stop button
        self.center_pane.grid_columnconfigure(0, weight=1)
        self.center_pane.grid_columnconfigure(1, weight=0) # for upscale value

        self.add_files_button = ctk.CTkButton(self.center_pane, text="Add Files", command=self.add_files)
        self.add_files_button.grid(row=0, column=0, columnspan=2, padx=10, pady=(10,5), sticky="ew")

        self.add_directory_button = ctk.CTkButton(self.center_pane, text="Add Directory", command=self.add_directory)
        self.add_directory_button.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        self.refresh_inputs_button = ctk.CTkButton(self.center_pane, text="Refresh Inputs", command=self.refresh_all_inputs)
        self.refresh_inputs_button.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        self.status_display = ctk.CTkTextbox(self.center_pane, wrap="word", state="disabled", height=200)
        self.status_display.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="nsew")

        ctk.CTkLabel(self.center_pane, text="Upscale:").grid(row=4, column=0, padx=(10,0), pady=(10,0), sticky="w")
        
        self.upscale_slider_frame = ctk.CTkFrame(self.center_pane, fg_color="transparent")
        self.upscale_slider_frame.grid(row=5, column=0, columnspan=2, padx=0, pady=5, sticky="ew")
        self.upscale_slider_frame.grid_columnconfigure(0, weight=1)

        self.upscale_slider = ctk.CTkSlider(self.upscale_slider_frame, from_=1, to=8, number_of_steps=28, command=self.update_upscale_label)
        self.upscale_slider.set(4)
        self.upscale_slider.grid(row=0, column=0, padx=(10,5), pady=5, sticky="ew")

        self.upscale_value_label = ctk.CTkLabel(self.upscale_slider_frame, text="x 4.0", width=40)
        self.upscale_value_label.grid(row=0, column=1, padx=(0,10), pady=5, sticky="e")

        self.start_stop_button = ctk.CTkButton(self.center_pane, text="Start Upscaling", command=self.toggle_processing)
        self.start_stop_button.grid(row=6, column=0, columnspan=2, padx=10, pady=(5,10), sticky="ew")

        # --- Output Pane ---
        self.output_pane = ctk.CTkFrame(self.main_frame)
        self.output_pane.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
        self.output_pane.grid_rowconfigure(0, weight=1)
        self.output_pane.grid_columnconfigure(0, weight=1)

        self.output_tabview = ctk.CTkTabview(self.output_pane)
        self.output_tabview.pack(expand=True, fill="both", padx=5, pady=5)
        self.output_tabview.add("Photos")
        self.output_tabview.add("Illustrations")

        self.output_photos_scrollable_frame = ctk.CTkScrollableFrame(self.output_tabview.tab("Photos"), label_text="Output Photos")
        self.output_photos_scrollable_frame.pack(expand=True, fill="both", padx=5, pady=5)

        self.output_anime_scrollable_frame = ctk.CTkScrollableFrame(self.output_tabview.tab("Illustrations"), label_text="Output Illustrations")
        self.output_anime_scrollable_frame.pack(expand=True, fill="both", padx=5, pady=5)

        # --- Initial Load and Queue Check ---
        self.refresh_all_inputs() # Load initial inputs
        self.after(100, self.check_output_queue)

    def handle_drop(self, event, target_tab_name):
        if self.is_processing: return
        # event.data is a string containing space-separated, brace-enclosed file paths
        # e.g., '{C:/path/to/file one.png} {D:/path/to/file_two.jpg}'
        raw_paths = event.data
        filepaths = []
        # Basic parsing for paths, works for paths without braces inside them
        current_path = ""
        in_brace = False
        for char in raw_paths:
            if char == '{':
                in_brace = True
                current_path = ""
            elif char == '}':
                in_brace = False
                if current_path:
                    filepaths.append(current_path)
                current_path = ""
            elif in_brace:
                current_path += char
        
        # Fallback for simple space-separated paths if parsing fails or for simpler dnd libs
        if not filepaths and '{' not in raw_paths and '}' not in raw_paths:
            filepaths = raw_paths.split()

        valid_filepaths = [fp for fp in filepaths if os.path.isfile(fp)]
        if valid_filepaths:
            self._add_paths_to_list(valid_filepaths, target_tab_name)
        else:
            self.update_status("Drag & Drop: No valid files found in drop.")


    def update_status(self, message):
        self.status_display.configure(state="normal")
        self.status_display.insert("end", str(message) + "\n")
        self.status_display.see("end")
        self.status_display.configure(state="disabled")

    def get_active_input_tab_name(self):
        try:
            return self.input_tabview.get() # "Photos" or "Illustrations"
        except Exception: # If tabview is not yet fully initialized or no tab is selected
            return "Photos" # Default

    def add_files(self):
        if self.is_processing: return
        active_input_tab_name = self.get_active_input_tab_name()
        filepaths = filedialog.askopenfilenames(
            title=f"Select {active_input_tab_name} Files",
            filetypes=(("Image files", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*"))
        )
        if filepaths:
            self._add_paths_to_list(filepaths, active_input_tab_name)

    def add_directory(self):
        if self.is_processing: return
        active_input_tab_name = self.get_active_input_tab_name()
        dirpath = filedialog.askdirectory(title=f"Select {active_input_tab_name} Directory")
        if dirpath:
            filepaths = []
            for item in os.listdir(dirpath):
                full_path = os.path.join(dirpath, item)
                if os.path.isfile(full_path) and full_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    filepaths.append(full_path)
            if filepaths:
                self._add_paths_to_list(filepaths, active_input_tab_name)

    def _add_paths_to_list(self, filepaths, tab_name):
        if tab_name == "Photos":
            target_map = self.photo_input_paths
            target_frame = self.input_photos_scrollable_frame
            display_name_prefix = "P-" # To ensure unique keys if same filename in both cats
        else: # Illustrations
            target_map = self.anime_input_paths
            target_frame = self.input_anime_scrollable_frame
            display_name_prefix = "A-"
        
        new_files_added_count = 0
        for fp_raw in filepaths:
            abs_path = os.path.abspath(fp_raw)
            display_key = display_name_prefix + os.path.basename(abs_path) # Use a unique key
            
            if display_key not in target_map:
                target_map[display_key] = abs_path
                self.display_thumbnail(abs_path, target_frame, display_key) # Pass key for removal
                new_files_added_count += 1

        if new_files_added_count > 0:
            self.update_status(f"Added {new_files_added_count} new file(s) to {tab_name} input.")
        elif filepaths: # Files were provided but all were duplicates
            self.update_status(f"All selected files already in {tab_name} input.")


    def display_thumbnail(self, file_path, parent_frame, display_key):
        try:
            img = Image.open(file_path)
            img.thumbnail(THUMBNAIL_SIZE)
            # For CTkImage, ensure img is not garbage collected if ImageTk is needed internally by CTkImage
            # No, CTkImage handles this.
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
            
            thumb_frame = ctk.CTkFrame(parent_frame) # Frame to hold image and remove button
            thumb_frame.pack(pady=2, padx=2, fill="x")

            label = ctk.CTkLabel(thumb_frame, image=ctk_img, text=os.path.basename(file_path), compound="top")
            label.pack(side="left", pady=2, padx=2)

            remove_button = ctk.CTkButton(thumb_frame, text="X", width=20, height=20,
                                          command=lambda k=display_key, pf=parent_frame, tf=thumb_frame: self.remove_input_item(k, pf, tf))
            remove_button.pack(side="right", padx=2, pady=2)
            
            # Store reference to image to prevent garbage collection issues with Tkinter PhotoImage
            # (Though CTkImage should handle this better)
            label.image = ctk_img 

        except Exception as e:
            self.update_status(f"Error loading thumbnail for {file_path}: {e}")
            # If thumbnail fails, still add a text entry that can be removed
            thumb_frame = ctk.CTkFrame(parent_frame)
            thumb_frame.pack(pady=2, padx=2, fill="x")
            error_label = ctk.CTkLabel(thumb_frame, text=f"Error: {os.path.basename(file_path)}", text_color="red")
            error_label.pack(side="left", pady=2, padx=2)
            remove_button = ctk.CTkButton(thumb_frame, text="X", width=20, height=20,
                                          command=lambda k=display_key, pf=parent_frame, tf=thumb_frame: self.remove_input_item(k, pf, tf))
            remove_button.pack(side="right", padx=2, pady=2)


    def remove_input_item(self, display_key, parent_frame, thumb_widget_frame):
        if display_key.startswith("P-"):
            if display_key in self.photo_input_paths:
                del self.photo_input_paths[display_key]
                self.update_status(f"Removed {display_key[2:]} from Photos input.")
        elif display_key.startswith("A-"):
            if display_key in self.anime_input_paths:
                del self.anime_input_paths[display_key]
                self.update_status(f"Removed {display_key[2:]} from Illustrations input.")
        
        thumb_widget_frame.destroy()


    def refresh_input_category(self, category_dir, category_name):
        # Clear current display for this category
        if category_name == "Photos":
            target_map = self.photo_input_paths
            scroll_frame = self.input_photos_scrollable_frame
        else: # Illustrations
            target_map = self.anime_input_paths
            scroll_frame = self.input_anime_scrollable_frame
        
        # Temporarily store keys to remove, to avoid modifying dict while iterating
        keys_to_remove = []
        for key, path_val in list(target_map.items()): # Use list() for safe iteration if modifying
            # Only remove items that were originally from the default input dir being refreshed
            # And are not found anymore. Or simply clear all and re-add.
            # For simplicity, let's clear all display and re-populate from map
            # No, better: clear map entries that were from this default dir.
            # This is tricky if user added files from elsewhere AND also from default dir
            # Safest: clear display, then repopulate map from dir, then add user-added files back
            # Current simpler approach: only add new files from dir, don't remove user-added ones.
            pass # Map items are managed by _add_paths_to_list and remove_input_item

        # Clear visual thumbnails first
        for widget in scroll_frame.winfo_children():
            widget.destroy()
        
        # Re-populate map and display from the default directory
        paths_from_dir = []
        if os.path.exists(category_dir):
            for item in os.listdir(category_dir):
                full_path = os.path.join(category_dir, item)
                if os.path.isfile(full_path) and full_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    paths_from_dir.append(os.path.abspath(full_path))
        
        # Add these paths (they will be added if not already in map, or ignored if duplicates based on key)
        if paths_from_dir:
            self._add_paths_to_list(paths_from_dir, category_name)
        
        # Now, re-display all items currently in the map for this category
        # This is needed because _add_paths_to_list only adds *new* thumbs.
        # And previous thumbs were cleared.
        current_map_paths = list(target_map.values()) # Get current state of paths after dir scan
        # Clear the map entries that are ONLY from this dir and might have been deleted from disk
        # This is still complex. Let's simplify:
        # The map (photo_input_paths, anime_input_paths) is the source of truth.
        # Refreshing adds files from default dirs if not already in map from elsewhere.
        
        # Rebuild thumbnails from the map which now includes dir contents
        temp_map_copy = dict(target_map) # Iterate over a copy
        target_map.clear() # Clear the map to re-populate cleanly with unique keys
        
        for abs_path in current_map_paths: #These are paths that were in map BEFORE dir rescan
             self._add_paths_to_list([abs_path], category_name) # Re-add to ensure correct key and display

        self.update_status(f"Refreshed {category_name} inputs. Found {len(paths_from_dir)} files in {category_dir}.")


    def refresh_all_inputs(self):
        if self.is_processing: return
        self.update_status("Refreshing all input lists...")
        
        # First clear visual displays
        for widget in self.input_photos_scrollable_frame.winfo_children(): widget.destroy()
        for widget in self.input_anime_scrollable_frame.winfo_children(): widget.destroy()
        
        # Temporarily save user-added paths that are NOT from default dirs
        # This is getting too complex for a simple refresh.
        # New strategy: Refresh just means "scan default dirs and add any new files found there"
        # User can manually remove items if they are deleted from disk.
        
        current_photo_paths = list(self.photo_input_paths.values())
        current_anime_paths = list(self.anime_input_paths.values())

        # Clear visual and internal lists before rescanning and re-adding
        for sf in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            for w in sf.winfo_children(): w.destroy()
        self.photo_input_paths.clear()
        self.anime_input_paths.clear()

        # Scan default photo directory
        if os.path.exists(INPUT_PHOTO_DIR):
            photo_dir_files = [os.path.abspath(os.path.join(INPUT_PHOTO_DIR, f))
                               for f in os.listdir(INPUT_PHOTO_DIR)
                               if os.path.isfile(os.path.join(INPUT_PHOTO_DIR, f))
                               and f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))]
            if photo_dir_files:
                self._add_paths_to_list(photo_dir_files, "Photos")

        # Scan default anime directory
        if os.path.exists(INPUT_ANIME_DIR):
            anime_dir_files = [os.path.abspath(os.path.join(INPUT_ANIME_DIR, f))
                               for f in os.listdir(INPUT_ANIME_DIR)
                               if os.path.isfile(os.path.join(INPUT_ANIME_DIR, f))
                               and f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))]
            if anime_dir_files:
                self._add_paths_to_list(anime_dir_files, "Illustrations")
        
        # Re-add previously listed paths (that might be from outside default dirs)
        # This prevents losing user's selections from arbitrary locations on refresh
        # _add_paths_to_list will handle duplicates correctly.
        if current_photo_paths:
            self._add_paths_to_list(current_photo_paths, "Photos")
        if current_anime_paths:
            self._add_paths_to_list(current_anime_paths, "Illustrations")

        self.update_status("Input lists refreshed.")


    def update_upscale_label(self, value):
        self.upscale_value_label.configure(text=f"x {float(value):.1f}")


    def clear_output_displays(self):
        for frame in [self.output_photos_scrollable_frame, self.output_anime_scrollable_frame]:
            for widget in frame.winfo_children():
                widget.destroy()
        self.update_status("Cleared output display.")

    def prepare_input_staging(self):
        staging_photo_dir = os.path.abspath(INPUT_PHOTO_DIR)
        staging_anime_dir = os.path.abspath(INPUT_ANIME_DIR)
        
        anything_staged_successfully = False
        any_source_files_were_selected = bool(self.photo_input_paths or self.anime_input_paths)

        # --- Process Photos ---
        desired_photo_sources = {}  # {basename: original_abs_path}
        if self.photo_input_paths:
            for original_abs_path in self.photo_input_paths.values():
                if not os.path.exists(original_abs_path):
                    self.update_status(f"Warning: Source photo not found: {original_abs_path}. Skipping.")
                    continue
                desired_photo_sources[os.path.basename(original_abs_path)] = original_abs_path
        
        if desired_photo_sources: # Only proceed if there are valid sources for this category
            os.makedirs(staging_photo_dir, exist_ok=True)
            current_files_in_staging_photo = {f for f in os.listdir(staging_photo_dir) if os.path.isfile(os.path.join(staging_photo_dir, f))}
            
            for basename, source_path in desired_photo_sources.items():
                dest_path_in_staging = os.path.join(staging_photo_dir, basename)
                copy_needed = True
                try:
                    if os.path.exists(dest_path_in_staging):
                        # os.path.samefile checks if two paths point to the exact same file inode
                        if os.path.samefile(source_path, dest_path_in_staging):
                            copy_needed = False  # Same file, already correctly in place
                    # else: dest_path_in_staging does not exist, so copy is needed.
                    
                    if copy_needed:
                        shutil.copy2(source_path, dest_path_in_staging) # copy2 preserves metadata
                    
                    anything_staged_successfully = True # Mark success if copy happened or wasn't needed
                    if basename in current_files_in_staging_photo:
                        current_files_in_staging_photo.remove(basename) # This file is desired, don't delete later

                except OSError as e: # os.path.samefile can raise OSError if a path doesn't exist during check
                    if not os.path.exists(source_path): # Source disappeared mid-operation
                        self.update_status(f"Source photo vanished: {source_path}. Cannot stage.")
                    elif not os.path.exists(dest_path_in_staging) and os.path.exists(source_path): # Dest didn't exist, so copy
                        try:
                            shutil.copy2(source_path, dest_path_in_staging)
                            anything_staged_successfully = True
                            if basename in current_files_in_staging_photo:
                                current_files_in_staging_photo.remove(basename)
                        except Exception as copy_e:
                            self.update_status(f"Error copying photo {source_path} to {dest_path_in_staging}: {copy_e}")
                    else: # Some other OSError
                        self.update_status(f"OS error processing photo {source_path} for staging: {e}")
                except Exception as e:
                    self.update_status(f"Error copying photo {source_path} to {dest_path_in_staging}: {e}")

            # Delete any files left in current_files_in_staging_photo (they are not in desired_photo_sources)
            for basename_to_delete in current_files_in_staging_photo:
                try:
                    os.remove(os.path.join(staging_photo_dir, basename_to_delete))
                except Exception as e:
                    self.update_status(f"Error deleting old staged photo {basename_to_delete} from {staging_photo_dir}: {e}")
        elif self.photo_input_paths: # User selected photos, but none were found on disk
             self.update_status("All selected photos were not found on disk.")


        # --- Process Anime (similar logic) ---
        desired_anime_sources = {}
        if self.anime_input_paths:
            for original_abs_path in self.anime_input_paths.values():
                if not os.path.exists(original_abs_path):
                    self.update_status(f"Warning: Source illustration not found: {original_abs_path}. Skipping.")
                    continue
                desired_anime_sources[os.path.basename(original_abs_path)] = original_abs_path

        if desired_anime_sources:
            os.makedirs(staging_anime_dir, exist_ok=True)
            current_files_in_staging_anime = {f for f in os.listdir(staging_anime_dir) if os.path.isfile(os.path.join(staging_anime_dir, f))}

            for basename, source_path in desired_anime_sources.items():
                dest_path_in_staging = os.path.join(staging_anime_dir, basename)
                copy_needed = True
                try:
                    if os.path.exists(dest_path_in_staging):
                        if os.path.samefile(source_path, dest_path_in_staging):
                            copy_needed = False
                    
                    if copy_needed:
                        shutil.copy2(source_path, dest_path_in_staging)
                    
                    anything_staged_successfully = True
                    if basename in current_files_in_staging_anime:
                        current_files_in_staging_anime.remove(basename)
                except OSError as e:
                    if not os.path.exists(source_path):
                        self.update_status(f"Source illustration vanished: {source_path}. Cannot stage.")
                    elif not os.path.exists(dest_path_in_staging) and os.path.exists(source_path):
                        try:
                            shutil.copy2(source_path, dest_path_in_staging)
                            anything_staged_successfully = True
                            if basename in current_files_in_staging_anime:
                                current_files_in_staging_anime.remove(basename)
                        except Exception as copy_e:
                            self.update_status(f"Error copying illustration {source_path} to {dest_path_in_staging}: {copy_e}")
                    else:
                        self.update_status(f"OS error processing illustration {source_path} for staging: {e}")
                except Exception as e:
                    self.update_status(f"Error copying illustration {source_path} to {dest_path_in_staging}: {e}")
            
            for basename_to_delete in current_files_in_staging_anime:
                try:
                    os.remove(os.path.join(staging_anime_dir, basename_to_delete))
                except Exception as e:
                    self.update_status(f"Error deleting old staged illustration {basename_to_delete} from {staging_anime_dir}: {e}")
        elif self.anime_input_paths: # User selected anime, but none were found on disk
            self.update_status("All selected illustrations were not found on disk.")


        # --- Determine overall success ---
        if not any_source_files_were_selected: # No files were in the input lists to begin with
            self.update_status("No files selected for input. Staging not required.")
            return True # Not an error, just nothing to do for staging.

        if anything_staged_successfully:
            self.update_status("Input file staging synchronized.")
            return True
        else:
            # This means files were selected, but none could be successfully staged (e.g., all sources missing or copy errors)
            self.update_status("Failed to stage any files. Check source file paths and permissions.")
            return False

    def toggle_processing(self):
        if self.is_processing:
            self.stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        self.clear_output_displays() 
        
        # Check if user added ANY files to the lists
        if not (self.photo_input_paths or self.anime_input_paths):
            self.update_status("Processing aborted: No input files have been added to the lists.")
            return

        # prepare_input_staging will now return False if staging fails (e.g. all selected sources are missing)
        # or True if staging is okay (including if nothing needed to be staged because valid sources were already in place or no sources were valid)
        if not self.prepare_input_staging():
            # prepare_input_staging() already prints detailed messages about why it might have failed.
            self.update_status("Processing aborted due to staging issues.")
            return

        # Additional check: after staging, are there actually any files in the staging dirs for upscale.py to find?
        # This is implicitly handled by upscale.py if it prints "no files found"
        # but we could add an explicit check here if desired. For now, let upscale.py report.

        self.is_processing = True
        self.start_stop_button.configure(text="Stop Processing", state="normal")
        self.add_files_button.configure(state="disabled")
        self.add_directory_button.configure(state="disabled")
        self.refresh_inputs_button.configure(state="disabled")
        # Disable remove buttons on thumbnails
        for scroll_frame in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            for thumb_frame in scroll_frame.winfo_children():
                if isinstance(thumb_frame, ctk.CTkFrame): # Our thumb_frame
                    for widget in thumb_frame.winfo_children():
                        if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "X":
                            widget.configure(state="disabled")

        self.upscale_slider.configure(state="disabled")
        self.status_display.configure(state="normal")
        self.status_display.delete("1.0", "end")
        self.status_display.configure(state="disabled")
        self.update_status("Starting upscaling process...")

        upscale_factor = self.upscale_slider.get()
        command = [PYTHON_EXECUTABLE, "upscale.py", "-u", str(upscale_factor)]

        self.processing_thread = threading.Thread(target=self.run_script, args=(command,), daemon=True)
        self.processing_thread.start()

    def run_script(self, command):
        try:
            # Ensure the script is found relative to the GUI script if it's in the same dir
            script_dir = os.path.dirname(os.path.abspath(__file__))
            upscale_script_path = os.path.join(script_dir, "upscale.py")
            if not os.path.exists(upscale_script_path):
                self.output_queue.put(f"ERROR: upscale.py not found at {upscale_script_path}")
                self.output_queue.put("__PROCESSING_COMPLETE__")
                return
            
            command[1] = upscale_script_path # Replace "upscale.py" with full path

            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                            text=True, bufsize=1, 
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                            cwd=script_dir) # Run script from its own directory
            
            for line in iter(self.process.stdout.readline, ''):
                self.output_queue.put(line)
            
            stderr_output = self.process.stderr.read()
            if stderr_output:
                self.output_queue.put(f"STDERR: {stderr_output}")

            self.process.stdout.close()
            self.process.stderr.close()
            self.process.wait()

        except Exception as e:
            self.output_queue.put(f"Error running script: {e}")
        finally:
            self.output_queue.put("__PROCESSING_COMPLETE__")


    def check_output_queue(self):
        try:
            while True:
                line = self.output_queue.get_nowait()
                if line == "__PROCESSING_COMPLETE__":
                    self.finish_processing()
                else:
                    self.update_status(line.strip())
        except queue.Empty:
            pass
        finally:
            self.after(100, self.check_output_queue)

    def stop_processing(self):
        if self.process and self.process.poll() is None:
            self.update_status("Attempting to stop processing...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
                self.update_status("Process terminated.")
            except subprocess.TimeoutExpired:
                self.update_status("Process did not terminate in time, killing.")
                self.process.kill()
                self.update_status("Process killed.")
            except Exception as e:
                self.update_status(f"Error during stop: {e}")
        
        self.finish_processing(stopped_manually=True)

    def finish_processing(self, stopped_manually=False):
        self.is_processing = False
        self.start_stop_button.configure(text="Start Upscaling", state="normal")
        self.add_files_button.configure(state="normal")
        self.add_directory_button.configure(state="normal")
        self.refresh_inputs_button.configure(state="normal")
        # Enable remove buttons on thumbnails
        for scroll_frame in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            for thumb_frame in scroll_frame.winfo_children():
                 if isinstance(thumb_frame, ctk.CTkFrame):
                    for widget in thumb_frame.winfo_children():
                        if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "X":
                            widget.configure(state="normal")

        self.upscale_slider.configure(state="normal")
        if not stopped_manually:
            self.update_status("Upscaling process finished.")
            self.load_output_thumbnails()
        else:
            self.update_status("Processing stopped by user.")
        self.process = None

    def load_output_thumbnails(self):
        self.update_status("Loading output thumbnails...")
        # Load Photo Outputs
        self._load_output_category(OUTPUT_PHOTO_DIR, self.output_photos_scrollable_frame)
        # Load Anime Outputs
        self._load_output_category(OUTPUT_ANIME_DIR, self.output_anime_scrollable_frame)
        self.update_status("Output thumbnails loaded.")

    def _load_output_category(self, output_dir, scroll_frame):
        if not os.path.exists(output_dir):
            self.update_status(f"Output directory not found: {output_dir}")
            return
            
        for widget in scroll_frame.winfo_children(): # Clear previous output thumbs
            widget.destroy()

        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath) and filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                try:
                    img = Image.open(filepath)
                    img.thumbnail(THUMBNAIL_SIZE)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
                    
                    label = ctk.CTkLabel(scroll_frame, image=ctk_img, text=filename, compound="top")
                    label.pack(pady=5, padx=5)
                    label.image = ctk_img # Keep ref
                except Exception as e:
                    self.update_status(f"Error loading output thumbnail {filepath}: {e}")

if __name__ == "__main__":
    # Make sure your dummy upscale.py is in the same directory as this script
    # or that PYTHON_EXECUTABLE can find your global upscale.py
    # Create dummy input dirs if they don't exist for initial scan
    os.makedirs(INPUT_PHOTO_DIR, exist_ok=True)
    os.makedirs(INPUT_ANIME_DIR, exist_ok=True)
    # Example: Create a dummy file in input_photo for testing initial load
    # with open(os.path.join(INPUT_PHOTO_DIR, "dummy_photo.txt"), "w") as f:
    #     f.write("This is a dummy file, use a real image for testing thumbnails.")

    app = App()
    app.mainloop()