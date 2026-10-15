"""Canvas fixture: text exists only as pixels (no UIA text), clicking it changes the drawing."""
import tkinter as tk

root = tk.Tk()
root.title("nitrolane canvas")
canvas = tk.Canvas(root, width=460, height=220, bg="white")
canvas.pack()
item = canvas.create_text(230, 110, text="Start Mission", font=("Segoe UI", 28, "bold"), fill="#1144aa")
canvas.tag_bind(item, "<Button-1>", lambda _e: canvas.itemconfig(item, text="Mission Done"))
root.after(120_000, root.destroy)
root.mainloop()
