import tkinter as tk

root = tk.Tk()
root.title("Keyboard Test")
root.geometry("400x200")

def key_press(event):
    print(f"PRESS: {event.keysym}, code={event.keycode}")

def key_release(event):
    print(f"RELEASE: {event.keysym}, code={event.keycode}")

root.bind_all("<KeyPress>", key_press)
root.bind_all("<KeyRelease>", key_release)

tk.Label(root, text="A・Dキーを押してください").pack(pady=50)

root.mainloop()