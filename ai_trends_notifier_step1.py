import sqlite3
import threading
import time
import datetime
import requests
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk
import io
import webbrowser
from plyer import notification
import schedule
import traceback

NEWSAPI_KEY = "1ab33ceb85fd4fca95ffe901348f191c"   
DB_PATH = "users.db"
NOTIFICATION_LIMIT = 4
MORNING_TIME = "09:00"
EVENING_TIME = "18:00"

try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS preferences (
            username TEXT PRIMARY KEY,
            industries TEXT
        )
    """)
    conn.commit()
    conn.close()

def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def validate_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    row = c.fetchone()
    conn.close()
    return bool(row)

def save_preferences(username, industries_list):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("REPLACE INTO preferences (username, industries) VALUES (?, ?)", (username, ",".join(industries_list)))
    conn.commit()
    conn.close()

def get_preferences(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT industries FROM preferences WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return row[0].split(",")
    return []

def send_notification(title, message):
    if not message:
        message = ""
    if len(message) > 250:
        message = message[:247] + "..."
    try:
        notification.notify(title=title, message=message, timeout=8)
    except Exception as e:
        print("Notification error:", e)


def fetch_news_for_industry(industry, page_size=6):
    """
    Fetch articles from NewsAPI. If NEWSAPI_KEY is empty, return sample data for testing.
    If industry == 'Global' it queries general AI news without adding the industry keyword.
    """
    if not NEWSAPI_KEY or NEWSAPI_KEY == "YOUR_NEWSAPI_KEY":
        now = datetime.datetime.now()
        return [
            {
                "title": f"{industry}: AI adoption rises in 2025",
                "description": f"Companies in {industry} are increasing use of AI to automate workflows and improve insights.",
                "url": "https://example.com/article1",
                "urlToImage": None,
                "source": {"name": "ExampleNews"},
                "publishedAt": now.isoformat()
            },
            {
                "title": f"{industry}: New AI model improves predictions",
                "description": f"A new model tailored for {industry} gives better predictions with fewer labels.",
                "url": "https://example.com/article2",
                "urlToImage": None,
                "source": {"name": "ExampleNews"},
                "publishedAt": (now - datetime.timedelta(hours=2)).isoformat()
            }
        ][:page_size]

    if industry == "Global":
        q = "artificial intelligence OR AI"
    else:
        q = f"artificial intelligence {industry}"
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY
    }
    resp = requests.get(url, params=params, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    return data.get("articles", [])


def prepare_preview(article):
    title = article.get("title") or "No title"
    desc = article.get("description") or article.get("content") or ""
    if desc and len(desc) > 280:
        desc = desc[:277] + "..."
    return title, desc

# Scheduler & notifier 
def gather_and_notify(username):
    industries = get_preferences(username)
    if not industries:
        print(f"[{username}] No industries selected.")
        return
    all_articles = []
    seen = set()
    for ind in industries:
        try:
            arts = fetch_news_for_industry(ind, page_size=6)
            for a in arts:
                # skip duplicates by URL
                u = a.get('url')
                if u and u in seen:
                    continue
                if u:
                    seen.add(u)
                a["_industry"] = ind
            all_articles.extend([a for a in arts if a.get('url') not in (None if None else set())])
            # Note: the list comprehension above just keeps the pipeline similar; dedupe handled via 'seen'
        except Exception as e:
            print(f"Error fetching for {ind}: {e}")
    if not all_articles:
        send_notification("AI Trends", "No articles found at the moment.")
        return
    try:
        all_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    except Exception:
        pass
    top = all_articles[:NOTIFICATION_LIMIT]
    msgs = []
    for art in top:
        t, s = prepare_preview(art)
        msgs.append(f"{t} — {s}")
    combined = "\n\n".join(msgs)
    header = f"AI Trends — {', '.join(industries)}"
    send_notification(header, combined)


def start_scheduler(username, morning_time=MORNING_TIME, evening_time=EVENING_TIME):
    try:
        gather_and_notify(username)
    except Exception as e:
        print("Immediate fetch failed:", e)
    schedule.clear()
    schedule.every().day.at(morning_time).do(lambda: gather_and_notify(username))
    schedule.every().day.at(evening_time).do(lambda: gather_and_notify(username))
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print("Scheduler error:", e)
        time.sleep(30)

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Trends Notifier")
        self.root.geometry("520x560")
        self.current_user = None
        self.dark_bg = "#22262b"
        self.card_bg = "#2f3338"
        self.fg = "#f1f3f5"
        self.btn_bg = "#3e8ef7"
        self.root.configure(bg=self.dark_bg)
        self.image_cache = {}           
        self.latest_window = None       
        self.latest_inner = None
        self.latest_canvas = None
        self.latest_scrollbar = None
        self.show_btn = None
        self._build_login_frame()

    def clear_root(self):
        for w in self.root.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

    # --- Login screen
    def _build_login_frame(self):
        self.clear_root()
        frame = tk.Frame(self.root, bg=self.dark_bg, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="AI Trends Notifier", font=("Arial", 18, "bold"), bg=self.dark_bg, fg=self.fg).pack(pady=8)
        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)

        tk.Label(frame, text="Username:", bg=self.dark_bg, fg=self.fg).pack(anchor="w")
        self.entry_user = tk.Entry(frame, bg="#3b3f44", fg=self.fg, insertbackground=self.fg)
        self.entry_user.pack(fill="x", pady=6)

        tk.Label(frame, text="Password:", bg=self.dark_bg, fg=self.fg).pack(anchor="w")
        self.entry_pass = tk.Entry(frame, show="*", bg="#3b3f44", fg=self.fg, insertbackground=self.fg)
        self.entry_pass.pack(fill="x", pady=6)

        btn_frame = tk.Frame(frame, bg=self.dark_bg)
        btn_frame.pack(pady=12)
        tk.Button(btn_frame, text="Login", width=12, command=self.handle_login, bg=self.btn_bg, fg="white").pack(side="left", padx=6)
        tk.Button(btn_frame, text="Register", width=12, command=self._build_register_frame, bg="#6c757d", fg="white").pack(side="left", padx=6)

        tk.Label(frame, text="If first time: Register → select industries → Save", bg=self.dark_bg, fg="#bfc7cf").pack(pady=10)

    # --- Register screen
    def _build_register_frame(self):
        self.clear_root()
        frame = tk.Frame(self.root, bg=self.dark_bg, padx=12, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Create Account", font=("Arial", 16, "bold"), bg=self.dark_bg, fg=self.fg).pack(pady=6)

        tk.Label(frame, text="Username:", bg=self.dark_bg, fg=self.fg).pack(anchor="w")
        self.reg_user = tk.Entry(frame, bg="#3b3f44", fg=self.fg, insertbackground=self.fg)
        self.reg_user.pack(fill="x", pady=6)

        tk.Label(frame, text="Password:", bg=self.dark_bg, fg=self.fg).pack(anchor="w")
        self.reg_pass = tk.Entry(frame, show="*", bg="#3b3f44", fg=self.fg, insertbackground=self.fg)
        self.reg_pass.pack(fill="x", pady=6)

        tk.Button(frame, text="Create", command=self.handle_register, bg=self.btn_bg, fg="white").pack(pady=10)
        tk.Button(frame, text="Back to Login", command=self._build_login_frame, bg="#6c757d", fg="white").pack()

    def handle_register(self):
        u = self.reg_user.get().strip()
        p = self.reg_pass.get().strip()
        if not u or not p:
            messagebox.showerror("Error", "Enter username and password")
            return
        ok = create_user(u, p)
        if ok:
            messagebox.showinfo("Success", "Account created. Please select industries.")
            self.current_user = u
            self._build_industry_selection(preload=[])
        else:
            messagebox.showerror("Error", "Username already exists")

    def handle_login(self):
        u = self.entry_user.get().strip()
        p = self.entry_pass.get().strip()
        if not u or not p:
            messagebox.showerror("Error", "Enter username and password")
            return
        if validate_user(u, p):
            self.current_user = u
            prefs = get_preferences(u)
            if not prefs:
                messagebox.showinfo("Welcome", "Please select industries to follow.")
                self._build_industry_selection(preload=[])
            else:
                self._build_dashboard()
                threading.Thread(target=start_scheduler, args=(u,), daemon=True).start()
        else:
            messagebox.showerror("Login failed", "Invalid username or password")

    def _build_industry_selection(self, preload):
        self.clear_root()
        frame = tk.Frame(self.root, bg=self.dark_bg, padx=12, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text="Select Industries", font=("Arial", 16, "bold"), bg=self.dark_bg, fg=self.fg).pack(pady=6)

        self.industries = ["Global", "Healthcare", "Finance", "Education", "Manufacturing", "IT"]
        self.vars = {}
        for ind in self.industries:
            v = tk.IntVar(value=1 if ind in preload else 0)
            cb = tk.Checkbutton(frame, text=ind, variable=v, bg=self.dark_bg, fg=self.fg, selectcolor="#444", activebackground=self.dark_bg)
            cb.pack(anchor="w", pady=4)
            self.vars[ind] = v

        tk.Button(frame, text="Save Preferences", command=self.save_prefs, bg=self.btn_bg, fg="white").pack(pady=8)
        tk.Button(frame, text="Cancel", command=self._build_login_frame, bg="#6c757d", fg="white").pack()

    def save_prefs(self):
        selected = [ind for ind, v in self.vars.items() if v.get() == 1]
        if not selected:
            messagebox.showerror("Error", "Select at least one industry")
            return
        save_preferences(self.current_user, selected)
        messagebox.showinfo("Saved", f"Preferences saved: {', '.join(selected)}")
        self._build_dashboard()
        threading.Thread(target=start_scheduler, args=(self.current_user,), daemon=True).start()

    def _build_dashboard(self):
        self.clear_root()
        frame = tk.Frame(self.root, bg=self.dark_bg, padx=12, pady=12)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=f"Welcome, {self.current_user}", font=("Arial", 16, "bold"), bg=self.dark_bg, fg=self.fg).pack(pady=8)

        self.show_btn = tk.Button(frame, text="Show Latest Headlines Now", command=self.show_latest_threadsafe, bg=self.btn_bg, fg="white")
        self.show_btn.pack(pady=6)
        tk.Button(frame, text="Change Preferences", command=lambda: self._build_industry_selection_with_preload(), bg="#6c757d", fg="white").pack(pady=6)
        tk.Button(frame, text="Logout", command=self.logout, bg="#6c757d", fg="white").pack(pady=6)

        tk.Label(frame, text=f"App will notify at {MORNING_TIME} & {EVENING_TIME}", bg=self.dark_bg, fg="#bfc7cf").pack(pady=8)

    def _build_industry_selection_with_preload(self):
        prefs = get_preferences(self.current_user)
        self._build_industry_selection(preload=prefs)

    def logout(self):
        self.current_user = None
        messagebox.showinfo("Logged out", "You have been logged out.")
        try:
            if self.latest_window and self.latest_window.winfo_exists():
                self.latest_window.destroy()
        except Exception:
            pass
        self._build_login_frame()

    def show_latest_threadsafe(self):
        if self.show_btn:
            try:
                self.show_btn.config(state="disabled")
            except Exception:
                pass
        threading.Thread(target=self._fetch_then_show_latest, daemon=True).start()

    def _fetch_then_show_latest(self):
        try:
            industries = get_preferences(self.current_user)
            if not industries:
                self.root.after(0, lambda: messagebox.showerror("Error", "No preferences found."))
                return
            all_articles = []
            seen_urls = set()
            for ind in industries:
                try:
                    arts = fetch_news_for_industry(ind, page_size=8)
                    for a in arts:
                        u = a.get('url')
                        if u and u in seen_urls:
                            continue
                        if u:
                            seen_urls.add(u)
                        a["_industry"] = ind
                        all_articles.append(a)
                except Exception as e:
                    print("Fetch error:", e)
            if not all_articles:
                self.root.after(0, lambda: messagebox.showinfo("No articles", "No articles found."))
                return
            try:
                all_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
            except Exception:
                pass
            
            self.root.after(0, lambda: self._open_or_update_latest_window(all_articles))
        except Exception:
            traceback.print_exc()
            self.root.after(0, lambda: messagebox.showerror("Error", "Failed to fetch articles."))
        finally:
        
            self.root.after(0, lambda: self.show_btn.config(state="normal") if self.show_btn else None)

    def _open_or_update_latest_window(self, articles):
        
        if not (self.latest_window and self.latest_window.winfo_exists()):
            self.latest_window = tk.Toplevel(self.root)
            self.latest_window.title("Latest AI Headlines")
            self.latest_window.geometry("1000x700")
            self.latest_window.minsize(600, 400)
            self.latest_window.configure(bg=self.dark_bg)

            self.latest_canvas = tk.Canvas(self.latest_window, bg=self.dark_bg, highlightthickness=0)
            self.latest_scrollbar = tk.Scrollbar(self.latest_window, orient="vertical", command=self.latest_canvas.yview)
            self.latest_inner = tk.Frame(self.latest_canvas, bg=self.dark_bg)
            self.latest_inner_id = self.latest_canvas.create_window((0,0), window=self.latest_inner, anchor='nw')
            self.latest_canvas.configure(yscrollcommand=self.latest_scrollbar.set)
            self.latest_canvas.pack(side="left", fill="both", expand=True)
            self.latest_scrollbar.pack(side="right", fill="y")

            def on_canvas_configure(event):
                try:
                    self.latest_canvas.itemconfig(self.latest_inner_id, width=event.width)
                    self.latest_canvas.configure(scrollregion=self.latest_canvas.bbox("all"))
                except Exception:
                    pass
            self.latest_canvas.bind("<Configure>", on_canvas_configure)

            def _on_mousewheel(event):
                try:
                    self.latest_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except Exception:
                    pass
            self.latest_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        
        for child in list(self.latest_inner.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass

        
        self.image_cache = {}

        
        for art in articles:
            card = tk.Frame(self.latest_inner, bg=self.card_bg, padx=8, pady=8)
            card.pack(fill="x", pady=8, padx=10)

            row = tk.Frame(card, bg=self.card_bg)
            row.pack(fill="x")

            
            img_label = tk.Label(row, bg=self.card_bg)
            img_label.pack(side="left", padx=(0,10))

            img_url = art.get("urlToImage")
            if img_url:
                
                threading.Thread(target=self._load_image_async, args=(img_url, img_label), daemon=True).start()

            
            text_col = tk.Frame(row, bg=self.card_bg)
            text_col.pack(side="left", fill="both", expand=True)

            title = art.get("title") or "No title"
            url = art.get('url')
            
            title_lbl = tk.Label(text_col, text=title, bg=self.card_bg, fg=self.fg, font=("Arial", 12, "bold"), wraplength=760, justify="left", cursor=("hand2" if url else ""))
            title_lbl.pack(anchor="w")
            if url:
                def _open(u=url):
                    try:
                        webbrowser.open(u)
                    except Exception:
                        pass
                title_lbl.bind("<Button-1>", lambda e, u=url: _open(u))

                
                def on_enter(e, lbl=title_lbl):
                    try:
                        lbl.configure(font=("Arial", 12, "underline"))
                    except Exception:
                        pass
                def on_leave(e, lbl=title_lbl):
                    try:
                        lbl.configure(font=("Arial", 12, "bold"))
                    except Exception:
                        pass
                title_lbl.bind("<Enter>", on_enter)
                title_lbl.bind("<Leave>", on_leave)

            summary = art.get("description") or art.get("content") or ""
            if summary and len(summary) > 350:
                summary = summary[:347] + "..."
            meta = f"{art.get('_industry','')} • {art.get('source',{}).get('name','Unknown')} • {art.get('publishedAt','')[:10]}"
            meta_lbl = tk.Label(text_col, text=meta, bg=self.card_bg, fg="#bfc7cf", font=("Arial", 9))
            meta_lbl.pack(anchor="w", pady=(4,0))

            summary_lbl = tk.Label(text_col, text=summary, bg=self.card_bg, fg=self.fg, wraplength=760, justify="left")
            summary_lbl.pack(anchor="w", pady=(6,4))

            
            action_row = tk.Frame(text_col, bg=self.card_bg)
            action_row.pack(fill="x")
            if url:
                open_btn = tk.Button(action_row, text="Open Article", bg="#5aa9ff", fg="white",
                                     command=lambda u=url: webbrowser.open(u))
                open_btn.pack(side="left", padx=(0,6))
            source_lbl = tk.Label(action_row, text=art.get('source',{}).get('name',''), bg=self.card_bg, fg="#bfc7cf")
            source_lbl.pack(side="left", padx=6)

    
        self.latest_inner.update_idletasks()
        try:
            self.latest_canvas.configure(scrollregion=self.latest_canvas.bbox("all"))
        except Exception:
            pass

    def _load_image_async(self, url, img_label):
        """Download image in background thread, then assign to img_label on main thread."""
        try:
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            img_data = r.content
            pil = Image.open(io.BytesIO(img_data)).convert("RGB")
            pil.thumbnail((160, 100))
            photo = ImageTk.PhotoImage(pil)
            
            def assign():
                if img_label.winfo_exists():
                    img_label.configure(image=photo)
                    self.image_cache[url] = photo
            self.root.after(0, assign)
        except Exception:
            pass

def main():
    init_db()
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
