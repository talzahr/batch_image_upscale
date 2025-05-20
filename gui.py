import customtkinter as ctk
from tkinter import filedialog, Menu, messagebox # Added Menu and messagebox
from PIL import Image
try:
    from PIL import ImageTk
except ImportError:
    import ImageTk

import os
import shutil
import subprocess
import threading
import queue
from tkinterdnd2 import DND_FILES, TkinterDnD
import sys
import platform # For opening files cross-platform

# --- Configuration ---
THUMBNAIL_SIZE = (100, 100)
INPUT_PHOTO_DIR = "input_photo"
INPUT_ANIME_DIR = "input_anime"
OUTPUT_PHOTO_DIR = "output_photo"
OUTPUT_ANIME_DIR = "output_anime"
PYTHON_EXECUTABLE = sys.executable

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title("Real-ESRGAN Upscaler GUI")
        self.geometry("1200x750")

        self.photo_input_paths = {}
        self.anime_input_paths = {}
        # Store references to CTkImage objects for thumbnails to prevent GC issues if passed to Menu
        self.thumbnail_image_refs = {} # {display_key: ctk_image_object}

        self.processing_thread = None
        self.process = None
        self.is_processing = False
        self.output_queue = queue.Queue()

        for dir_path in [INPUT_PHOTO_DIR, INPUT_ANIME_DIR, OUTPUT_PHOTO_DIR, OUTPUT_ANIME_DIR]:
            os.makedirs(dir_path, exist_ok=True)

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(expand=True, fill="both")

        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=2)
        self.main_frame.grid_columnconfigure(2, weight=1)
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

        self.input_tabview.tab("Photos").drop_target_register(DND_FILES)
        self.input_tabview.tab("Photos").dnd_bind('<<Drop>>', lambda e: self.handle_drop(e, "Photos"))
        self.input_tabview.tab("Illustrations").drop_target_register(DND_FILES)
        self.input_tabview.tab("Illustrations").dnd_bind('<<Drop>>', lambda e: self.handle_drop(e, "Illustrations"))

        # --- Center Pane ---
        self.center_pane = ctk.CTkFrame(self.main_frame)
        self.center_pane.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.center_pane.grid_rowconfigure(0, weight=0)
        self.center_pane.grid_rowconfigure(1, weight=0)
        self.center_pane.grid_rowconfigure(2, weight=0)
        self.center_pane.grid_rowconfigure(3, weight=1)
        self.center_pane.grid_rowconfigure(4, weight=0)
        self.center_pane.grid_rowconfigure(5, weight=0)
        self.center_pane.grid_rowconfigure(6, weight=0)
        self.center_pane.grid_columnconfigure(0, weight=1)
        self.center_pane.grid_columnconfigure(1, weight=0)

        self.add_files_button = ctk.CTkButton(self.center_pane, text="Add Files", command=self.add_files)
        self.add_files_button.grid(row=0, column=0, columnspan=2, padx=10, pady=(10,5), sticky="ew")

        self.add_directory_button = ctk.CTkButton(self.center_pane, text="Add Directory", command=self.add_directory)
        self.add_directory_button.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="ew")
        
        self.refresh_inputs_button = ctk.CTkButton(self.center_pane, text="Refresh Input Lists", command=self.refresh_all_inputs)
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
        
        # Bind double-click for output panes
        #self.output_photos_scrollable_frame.bind_class("CTkLabel", "<Double-1>", self.open_image_from_output_event)
        #self.output_anime_scrollable_frame.bind_class("CTkLabel", "<Double-1>", self.open_image_from_output_event)


        self.refresh_all_inputs()
        self.after(100, self.check_output_queue)

    # --- Event Handlers and UI Actions ---


    # Modify display_thumbnail slightly:
    def display_thumbnail(self, file_path, parent_frame, display_key, is_input_thumb=True):
        try:
            img = Image.open(file_path)
            img.thumbnail(THUMBNAIL_SIZE)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
            
            self.thumbnail_image_refs[display_key] = ctk_img

            thumb_frame = ctk.CTkFrame(parent_frame) 
            thumb_frame.pack(pady=2, padx=2, fill="x") 

            ctk_label_widget = ctk.CTkLabel(thumb_frame, image=ctk_img, text=os.path.basename(file_path), compound="top")
            # Label now takes the full width of the thumb_frame as there's no X button
            ctk_label_widget.pack(side="left", pady=2, padx=2, expand=True, fill="both") 
            
            ctk_label_widget.original_path = file_path
            ctk_label_widget.display_key = display_key
            ctk_label_widget.parent_frame_ref = parent_frame 
            ctk_label_widget.thumb_widget_frame_ref = thumb_frame

            ctk_label_widget.bind("<Double-1>", lambda event, lbl=ctk_label_widget: self.open_image_event(event, custom_widget=lbl))

            if is_input_thumb:
                # --- REMOVE X BUTTON CREATION AND PACKING ---
                # remove_button = ctk.CTkButton(thumb_frame, text="X", width=20, height=20,
                #                             command=lambda k=display_key, pf=parent_frame, tf=thumb_frame: self.remove_input_item(k, pf, tf))
                # remove_button.pack(side="right", padx=(0, 2), pady=2) 
                # --- END OF REMOVAL ---
                
                ctk_label_widget.bind("<Button-3>", lambda event, lbl=ctk_label_widget: self.show_input_context_menu(event, custom_widget=lbl))
            else: 
                ctk_label_widget.bind("<Button-3>", lambda event, lbl=ctk_label_widget: self.show_output_context_menu(event, custom_widget=lbl))
            
        except FileNotFoundError:
            self.update_status(f"Thumbnail Error: File not found at {file_path}")
            thumb_frame = ctk.CTkFrame(parent_frame) 
            thumb_frame.pack(pady=2, padx=2, fill="x")
            error_display_label = ctk.CTkLabel(thumb_frame, text=f"Not Found: {os.path.basename(file_path)}", text_color="red")
            error_display_label.pack(side="left", pady=2, padx=2, expand=True, fill="both")
            
            # Store necessary attributes on error label if it might be interactive later
            error_display_label.display_key = display_key
            error_display_label.parent_frame_ref = parent_frame
            error_display_label.thumb_widget_frame_ref = thumb_frame
            # No X button for error items either now
            # if is_input_thumb:
                # Context menu could still be bound to error_display_label if desired
                # error_display_label.bind("<Button-3>", lambda event, lbl=error_display_label: self.show_input_context_menu(event, custom_widget=lbl))


        except Exception as e:
            self.update_status(f"Error loading thumbnail for {file_path}: {e}")
            thumb_frame = ctk.CTkFrame(parent_frame)
            thumb_frame.pack(pady=2, padx=2, fill="x")
            error_display_label = ctk.CTkLabel(thumb_frame, text=f"Error: {os.path.basename(file_path)}", text_color="red")
            error_display_label.pack(side="left", pady=2, padx=2, expand=True, fill="both")

            error_display_label.display_key = display_key
            error_display_label.parent_frame_ref = parent_frame
            error_display_label.thumb_widget_frame_ref = thumb_frame
            # No X button for error items either now
            # if is_input_thumb:
                # error_display_label.bind("<Button-3>", lambda event, lbl=error_display_label: self.show_input_context_menu(event, custom_widget=lbl))

    def open_image_event(self, event, custom_widget=None): # Added custom_widget
        # event.widget might be an internal part, custom_widget is our actual CTkLabel
        target_widget = custom_widget if custom_widget else event.widget 
        print(f"DEBUG: open_image_event. event.widget: {event.widget}, custom_widget: {target_widget}")

        if hasattr(target_widget, 'original_path'):
            self.open_image_with_default_viewer(target_widget.original_path)
        else:
            print(f"DEBUG: open_image_event - target_widget has no original_path: {target_widget}")

    # def open_image_from_output_event(self, event):
        # widget = event.widget
        # # For output, original_path is set directly on the label during _load_output_category
        # if hasattr(widget, 'original_path'):
            # self.open_image_with_default_viewer(widget.original_path)

    def open_image_with_default_viewer(self, file_path):
        try:
            if not os.path.exists(file_path):
                self.update_status(f"Cannot open: File not found at {file_path}")
                messagebox.showerror("Error", f"File not found:\n{file_path}")
                return

            self.update_status(f"Opening {file_path}...")
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin": # macOS
                subprocess.call(['open', file_path])
            else: # Linux and other Unix-like
                subprocess.call(['xdg-open', file_path])
        except Exception as e:
            self.update_status(f"Error opening {file_path}: {e}")
            messagebox.showerror("Error", f"Could not open image:\n{e}")

    def show_input_context_menu(self, event, custom_widget=None):
        target_widget = custom_widget if custom_widget else event.widget
        # print(f"DEBUG: show_input_context_menu CALLED. event.widget: {event.widget}, custom_widget: {target_widget}") 
        
        if not hasattr(target_widget, 'display_key') or not hasattr(target_widget, 'original_path'):
            # print(f"DEBUG: show_input_context_menu - target_widget missing attributes: {target_widget}")
            return

        display_key = target_widget.display_key
        original_path = target_widget.original_path
        parent_frame_ref = target_widget.parent_frame_ref 
        thumb_widget_frame_ref = target_widget.thumb_widget_frame_ref

        context_menu = Menu(self, tearoff=0)
        context_menu.add_command(label="Open Image", 
                                 command=lambda p=original_path: self.open_image_with_default_viewer(p))
        
        # --- ADD "OPEN CONTAINING FOLDER" ---
        containing_folder = os.path.dirname(original_path)
        context_menu.add_command(label="Open Containing Folder",
                                 command=lambda d=containing_folder: self.open_image_with_default_viewer(d)) # Re-use for opening directory
        # --- END OF ADDITION ---

        context_menu.add_separator() # Keep separator before destructive actions
        context_menu.add_command(label="Remove from List", 
                                 command=lambda k=display_key, pf=parent_frame_ref, tf=thumb_widget_frame_ref: self.remove_input_item(k, pf, tf))
        context_menu.add_command(label="Delete from Disk...", 
                                 command=lambda k=display_key, p=original_path, pf=parent_frame_ref, tf=thumb_widget_frame_ref: self.delete_file_from_disk(k, p, pf, tf))
        
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()
            
    def show_output_context_menu(self, event, custom_widget=None):
        target_widget = custom_widget if custom_widget else event.widget
        print(f"DEBUG: show_output_context_menu CALLED. event.widget: {event.widget}, custom_widget: {target_widget}")
        
        if not hasattr(target_widget, 'original_path'): # 'original_path' is the key for output items
            print(f"DEBUG: show_output_context_menu - target_widget missing original_path: {target_widget}")
            return

        original_path = target_widget.original_path # This is the path to the output file

        context_menu = Menu(self, tearoff=0)
        context_menu.add_command(label="Open Image", 
                                 command=lambda p=original_path: self.open_image_with_default_viewer(p))
        
        # Optionally, add "Open Output Directory"
        output_dir = os.path.dirname(original_path)
        context_menu.add_command(label="Open Output Directory",
                                 command=lambda d=output_dir: self.open_image_with_default_viewer(d)) # Re-use viewer for dirs

        # Optionally, add "Delete from Disk" for output files too
        # For this, we'd need a display_key and reference to the thumb_widget_frame if we want UI removal
        # For now, let's keep it simple. If delete is needed, it would mirror input's delete logic.
        
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()            

    def remove_input_item(self, display_key, parent_frame, thumb_widget_frame, from_disk_deletion=False):
        item_removed = False
        path_to_remove = None

        if display_key in self.photo_input_paths:
            path_to_remove = self.photo_input_paths[display_key]
            del self.photo_input_paths[display_key]
            item_removed = True
            category = "Photos"
        elif display_key in self.anime_input_paths:
            path_to_remove = self.anime_input_paths[display_key]
            del self.anime_input_paths[display_key]
            item_removed = True
            category = "Illustrations"
        
        if display_key in self.thumbnail_image_refs: # Clean up image ref
            del self.thumbnail_image_refs[display_key]

        if item_removed:
            if not from_disk_deletion: # Avoid double message if called from delete_file_from_disk
                 self.update_status(f"Removed {os.path.basename(path_to_remove)} from {category} input list.")
            thumb_widget_frame.destroy()
        else:
            self.update_status(f"Item {display_key} not found in input lists for removal.")
        
        return path_to_remove # Return path if needed by caller (e.g., delete_from_disk)


    def delete_file_from_disk(self, display_key, file_path, parent_frame, thumb_widget_frame):
        if not os.path.exists(file_path):
            messagebox.showerror("Error", f"File no longer exists on disk:\n{file_path}")
            # Still remove from list if it's there
            self.remove_input_item(display_key, parent_frame, thumb_widget_frame, from_disk_deletion=True)
            return

        confirm = messagebox.askyesno("Confirm Delete", 
                                      f"Are you sure you want to permanently delete this file from your disk?\n\n{file_path}")
        if confirm:
            try:
                os.remove(file_path)
                self.update_status(f"Successfully deleted from disk: {file_path}")
                # Now remove from the UI list (passing from_disk_deletion=True to suppress redundant message)
                self.remove_input_item(display_key, parent_frame, thumb_widget_frame, from_disk_deletion=True)
            except Exception as e:
                self.update_status(f"Error deleting file {file_path} from disk: {e}")
                messagebox.showerror("Delete Error", f"Could not delete file:\n{e}")
        else:
            self.update_status(f"Deletion cancelled for {file_path}")

    # --- Helper to get path for output thumbnails ---
    # (This is slightly adjusted in _load_output_category)

    # ... (handle_drop, update_status, get_active_input_tab_name, add_files, add_directory, _add_paths_to_list - mostly same)
    # Minor change in _add_paths_to_list to call the modified display_thumbnail

    def handle_drop(self, event, target_tab_name):
        if self.is_processing: return
        raw_paths = event.data
        filepaths = []
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
            return self.input_tabview.get() 
        except Exception: 
            return "Photos" 

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
            display_name_prefix = "P-" 
        else: 
            target_map = self.anime_input_paths
            target_frame = self.input_anime_scrollable_frame
            display_name_prefix = "A-"
        
        new_files_added_count = 0
        for fp_raw in filepaths:
            abs_path = os.path.abspath(fp_raw)
            # Use filename as part of key, prefix ensures uniqueness across categories
            display_key = display_name_prefix + os.path.basename(abs_path) + "_" + str(hash(abs_path)) # Add hash for more uniqueness if same name different dir

            # Check if this specific absolute path is already represented, even if key differs due to hash
            path_already_exists = False
            for existing_abs_path in target_map.values():
                if os.path.samefile(existing_abs_path, abs_path): # Check if paths point to same file
                    path_already_exists = True
                    # Update display_key if a different key for the same file exists
                    # (This part can be complex if multiple identical files from different source paths were added)
                    # For simplicity, we'll just prevent adding the same actual file twice.
                    break
            
            if not path_already_exists:
                target_map[display_key] = abs_path
                self.display_thumbnail(abs_path, target_frame, display_key, is_input_thumb=True) # Pass True
                new_files_added_count += 1
            elif display_key not in target_map: # Same file, but maybe the display key changed (e.g. after refresh)
                # Find old key and update it, or just ensure it's in target_map
                # For simplicity, if path exists, assume it's handled
                pass


        if new_files_added_count > 0:
            self.update_status(f"Added {new_files_added_count} new file(s) to {tab_name} input.")
        elif filepaths: 
            self.update_status(f"All selected files already in {tab_name} input or are duplicates of existing files.")

    # --- refresh_all_inputs, update_upscale_label - mostly same ---

    def refresh_all_inputs(self):
        if self.is_processing: return
        self.update_status("Refreshing all input lists...")
        
        # Store current user selections to re-add them after clearing and scanning default dirs
        # This ensures files added from arbitrary locations are not lost on refresh.
        # We store absolute paths to avoid issues with relative paths.
        
        # 1. Get all unique absolute paths currently in the lists
        all_current_abs_paths_photos = set(os.path.abspath(p) for p in self.photo_input_paths.values())
        all_current_abs_paths_anime = set(os.path.abspath(p) for p in self.anime_input_paths.values())

        # 2. Clear visual displays and internal path maps
        for sf in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            for w in sf.winfo_children(): w.destroy()
        self.photo_input_paths.clear()
        self.anime_input_paths.clear()
        self.thumbnail_image_refs.clear()


        # 3. Scan default input directories and add their contents
        # These will be added first. _add_paths_to_list handles duplicates.
        def scan_and_add(default_dir, category_name):
            if os.path.exists(default_dir):
                dir_files = [os.path.abspath(os.path.join(default_dir, f))
                                   for f in os.listdir(default_dir)
                                   if os.path.isfile(os.path.join(default_dir, f))
                                   and f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp'))]
                if dir_files:
                    self._add_paths_to_list(dir_files, category_name)

        scan_and_add(INPUT_PHOTO_DIR, "Photos")
        scan_and_add(INPUT_ANIME_DIR, "Illustrations")

        # 4. Re-add the user's original selections (which might be from outside default dirs)
        # _add_paths_to_list will ensure that if a file was already added from default dir scan,
        # it won't be added again visually, but its original path source is maintained.
        if all_current_abs_paths_photos:
            self._add_paths_to_list(list(all_current_abs_paths_photos), "Photos")
        if all_current_abs_paths_anime:
            self._add_paths_to_list(list(all_current_abs_paths_anime), "Illustrations")
            
        self.update_status("Input lists refreshed.")

    def update_upscale_label(self, value):
        self.upscale_value_label.configure(text=f"x {float(value):.1f}")
    
    # --- prepare_input_staging, toggle_processing, start_processing, run_script, check_output_queue, stop_processing, finish_processing - same ---
    # (No changes needed in these core processing functions for these UI features)
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
        
        if desired_photo_sources: 
            os.makedirs(staging_photo_dir, exist_ok=True)
            current_files_in_staging_photo = {f for f in os.listdir(staging_photo_dir) if os.path.isfile(os.path.join(staging_photo_dir, f))}
            
            for basename, source_path in desired_photo_sources.items():
                dest_path_in_staging = os.path.join(staging_photo_dir, basename)
                copy_needed = True
                try:
                    if os.path.exists(dest_path_in_staging):
                        if os.path.samefile(source_path, dest_path_in_staging):
                            copy_needed = False  
                    
                    if copy_needed:
                        shutil.copy2(source_path, dest_path_in_staging) 
                    
                    anything_staged_successfully = True 
                    if basename in current_files_in_staging_photo:
                        current_files_in_staging_photo.remove(basename) 

                except OSError as e: 
                    if not os.path.exists(source_path): 
                        self.update_status(f"Source photo vanished: {source_path}. Cannot stage.")
                    elif not os.path.exists(dest_path_in_staging) and os.path.exists(source_path): 
                        try:
                            shutil.copy2(source_path, dest_path_in_staging)
                            anything_staged_successfully = True
                            if basename in current_files_in_staging_photo:
                                current_files_in_staging_photo.remove(basename)
                        except Exception as copy_e:
                            self.update_status(f"Error copying photo {source_path} to {dest_path_in_staging}: {copy_e}")
                    else: 
                        self.update_status(f"OS error processing photo {source_path} for staging: {e}")
                except Exception as e:
                    self.update_status(f"Error copying photo {source_path} to {dest_path_in_staging}: {e}")

            for basename_to_delete in current_files_in_staging_photo:
                try:
                    os.remove(os.path.join(staging_photo_dir, basename_to_delete))
                except Exception as e:
                    self.update_status(f"Error deleting old staged photo {basename_to_delete} from {staging_photo_dir}: {e}")
        elif self.photo_input_paths: 
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
        elif self.anime_input_paths: 
            self.update_status("All selected illustrations were not found on disk.")

        if not any_source_files_were_selected: 
            self.update_status("No files selected for input. Staging not required.")
            return True 

        if anything_staged_successfully:
            self.update_status("Input file staging synchronized.")
            return True
        else:
            self.update_status("Failed to stage any files. Check source file paths and permissions.")
            return False

    def toggle_processing(self):
        if self.is_processing:
            self.stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        self.clear_output_displays() 
        
        if not (self.photo_input_paths or self.anime_input_paths):
            self.update_status("Processing aborted: No input files have been added to the lists.")
            return

        if not self.prepare_input_staging():
            self.update_status("Processing aborted due to staging issues.")
            return

        self.is_processing = True
        self.start_stop_button.configure(text="Stop Processing", state="normal")
        self.add_files_button.configure(state="disabled")
        self.add_directory_button.configure(state="disabled")
        self.refresh_inputs_button.configure(state="disabled")
        # for scroll_frame in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            # for thumb_frame_widget in scroll_frame.winfo_children(): # Iterate over the CTkFrames we packed
                # if isinstance(thumb_frame_widget, ctk.CTkFrame):
                    # for widget in thumb_frame_widget.winfo_children():
                        # if isinstance(widget, ctk.CTkButton) and widget.cget("text") == "X":
                            # widget.configure(state="disabled")
                        # # Disable context menu on labels during processing
                        # if isinstance(widget, ctk.CTkLabel):
                            # widget.unbind("<Button-3>")


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
            script_dir = os.path.dirname(os.path.abspath(__file__))
            upscale_script_path = os.path.join(script_dir, "upscale.py")
            if not os.path.exists(upscale_script_path):
                self.output_queue.put(f"ERROR: upscale.py not found at {upscale_script_path}")
                self.output_queue.put("__PROCESSING_COMPLETE__")
                return
            
            command[1] = upscale_script_path 

            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                            text=True, bufsize=1, 
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                            cwd=script_dir) 
            
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
        
        # Re-enable remove buttons and context menus on input thumbnails
        # for scroll_frame in [self.input_photos_scrollable_frame, self.input_anime_scrollable_frame]:
            # for thumb_frame_widget in scroll_frame.winfo_children(): # These are the CTkFrames we packed
                # if isinstance(thumb_frame_widget, ctk.CTkFrame): # Our specific container for label + button
                    # found_label_in_thumb_frame = False
                    # for widget_in_thumb in thumb_frame_widget.winfo_children():
                        # if isinstance(widget_in_thumb, ctk.CTkButton) and widget_in_thumb.cget("text") == "X":
                            # widget_in_thumb.configure(state="normal")
                        # # Find the CTkLabel that has our custom attributes (original_path etc.)
                        # # and re-bind the context menu to it.
                        # elif isinstance(widget_in_thumb, ctk.CTkLabel) and hasattr(widget_in_thumb, 'original_path'):
                            # # Make sure we are rebinding to the correct label instance
                            # # The lambda will capture the current 'widget_in_thumb' (our ctk_label_widget)
                            # widget_in_thumb.bind("<Button-3>", lambda event, lbl=widget_in_thumb: self.show_input_context_menu(event, custom_widget=lbl))
                            # found_label_in_thumb_frame = True
                    # # if not found_label_in_thumb_frame:
                        # # print(f"DEBUG: finish_processing - No interactive CTkLabel found in thumb_frame: {thumb_frame_widget}")


        self.upscale_slider.configure(state="normal")
        if not stopped_manually:
            self.update_status("Upscaling process finished.")
            self.load_output_thumbnails() # This is where the issue might be triggered
        else:
            self.update_status("Processing stopped by user.")
        self.process = None

    def clear_output_displays(self): # Added to avoid confusion with clear_staging_dirs
        for frame in [self.output_photos_scrollable_frame, self.output_anime_scrollable_frame]:
            for widget in frame.winfo_children():
                widget.destroy()
        self.update_status("Cleared output display.")

    def load_output_thumbnails(self):
        self.update_status("Loading output thumbnails...")
        self._load_output_category(OUTPUT_PHOTO_DIR, self.output_photos_scrollable_frame)
        self._load_output_category(OUTPUT_ANIME_DIR, self.output_anime_scrollable_frame)
        self.update_status("Output thumbnails loaded.")

    def _load_output_category(self, output_dir, scroll_frame):
        if not os.path.exists(output_dir):
            self.update_status(f"Output directory not found: {output_dir}")
            return
            
        for widget in scroll_frame.winfo_children():
            widget.destroy()

        for filename in os.listdir(output_dir):
            filepath = os.path.join(output_dir, filename)
            if os.path.isfile(filepath) and filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                # For output thumbnails, display_key is not strictly needed for removal in same way,
                # but good for consistency if we ever add context menus there.
                display_key = "OUT-" + filename 
                self.display_thumbnail(filepath, scroll_frame, display_key, is_input_thumb=False)


if __name__ == "__main__":
    os.makedirs(INPUT_PHOTO_DIR, exist_ok=True)
    os.makedirs(INPUT_ANIME_DIR, exist_ok=True)
    app = App()
    app.mainloop()