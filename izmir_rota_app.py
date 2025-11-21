import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.pyplot as plt
import osmnx as ox
import networkx as nx
import os

# --- AYARLAR ---
GRAPHML_FILE = "izmir_yol_agi.graphml"
PLACE_NAME = "Konak, İzmir, Türkiye"

LOCATIONS = {
    "Konak Saat Kulesi": (38.4192, 27.1287),
    "Hükümet Konağı": (38.4198, 27.1295),
    "Alsancak Garı": (38.4385, 27.1470),
    "Kültürpark (Lozan Kapısı)": (38.4276, 27.1435),
    "Konak Pier": (38.4223, 27.1275),
    "Tarihi Asansör": (38.4086, 27.1174),
    "Basmane Garı": (38.4244, 27.1433),
    "Gündoğdu Meydanı": (38.4337, 27.1369),
    "Fahrettin Altay Metro": (38.39657, 27.07093),
    "Halkapınar": (38.41972, 27.15906)
}

class HaritaKontrolcusu:
    """Harita üzerinde Zoom ve Pan işlemlerini yöneten sınıf."""
    def __init__(self, ax, canvas):
        self.ax = ax
        self.canvas = canvas
        self.press = None # Tıklama anındaki koordinatları tutar
        self.cur_xlim = None
        self.cur_ylim = None
        self.x0 = None
        self.y0 = None
        self.x1 = None
        self.y1 = None
        self.xpress = None
        self.ypress = None

        # Olayları Bağla
        self.canvas.mpl_connect('scroll_event', self.on_scroll) # Tekerlek
        self.canvas.mpl_connect('button_press_event', self.on_press) # Tıklama
        self.canvas.mpl_connect('button_release_event', self.on_release) # Bırakma
        self.canvas.mpl_connect('motion_notify_event', self.on_motion) # Hareket

    def on_scroll(self, event):
        """Fare tekerleği ile zoom yapar."""
        if event.inaxes != self.ax: return

        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()

        xdata = event.xdata # Farenin olduğu X
        ydata = event.ydata # Farenin olduğu Y

        if xdata is None or ydata is None: return

        # Zoom Faktörü (1.1 = %10 büyüme/küçülme)
        base_scale = 1.2
        if event.button == 'up': # Yakınlaş
            scale_factor = 1 / base_scale
        elif event.button == 'down': # Uzaklaş
            scale_factor = base_scale
        else:
            scale_factor = 1

        # Yeni limitleri hesapla (Fare imleci merkezde kalacak şekilde)
        new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
        new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor

        relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
        rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])

        self.ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
        self.ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
        
        self.canvas.draw_idle()

    def on_press(self, event):
        """Tıklama anında başlangıç noktasını kaydeder."""
        if event.inaxes != self.ax: return
        
        # Sol tık (Pan başlat)
        if event.button == 1:
            self.press = self.x0, self.y0, event.xdata, event.ydata
            self.x0, self.y0, self.xpress, self.ypress = self.press
        
        # Sağ tık (Reset - İsteğe bağlı)
        if event.button == 3:
            self.ax.autoscale()
            self.canvas.draw_idle()

    def on_motion(self, event):
        """Fare sürüklendikçe haritayı kaydırır."""
        if self.press is None: return
        if event.inaxes != self.ax: return

        dx = event.xdata - self.xpress
        dy = event.ydata - self.ypress

        self.cur_xlim = self.ax.get_xlim()
        self.cur_ylim = self.ax.get_ylim()

        self.cur_xlim -= dx
        self.cur_ylim -= dy

        self.ax.set_xlim(self.cur_xlim)
        self.ax.set_ylim(self.cur_ylim)

        self.canvas.draw_idle()

    def on_release(self, event):
        """Bırakınca kaydırma işlemini bitirir."""
        self.press = None
        self.canvas.draw_idle()


class RotaUygulamasi:
    def __init__(self, root):
        self.root = root
        self.root.title("İzmir Akıllı Rota - İnteraktif (Zoom/Pan)")
        self.root.geometry("1100x850")
        
        self.G = None
        self.zoom_pan_handler = None # Kontrolcü değişkenimiz
        
        # --- ÜST PANEL ---
        control_frame = tk.Frame(root, bg="#e1e1e1", pady=10)
        control_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(control_frame, text="Başlangıç:", bg="#e1e1e1").pack(side=tk.LEFT, padx=5)
        self.start_combo = ttk.Combobox(control_frame, values=list(LOCATIONS.keys()), width=20, state="readonly")
        self.start_combo.current(0)
        self.start_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(control_frame, text="Bitiş:", bg="#e1e1e1").pack(side=tk.LEFT, padx=5)
        self.end_combo = ttk.Combobox(control_frame, values=list(LOCATIONS.keys()), width=20, state="readonly")
        self.end_combo.current(2)
        self.end_combo.pack(side=tk.LEFT, padx=5)

        self.calc_btn = tk.Button(control_frame, text="Rotayı Bul", command=self.hesapla, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
        self.calc_btn.pack(side=tk.LEFT, padx=15)

        # Kullanım Talimatı
        tk.Label(control_frame, text="(Tekerlek: Zoom | Sol Tık: Kaydır | Sağ Tık: Sıfırla)", font=("Arial", 8), fg="gray", bg="#e1e1e1").pack(side=tk.LEFT, padx=10)

        self.info_label = tk.Label(control_frame, text="Harita Bekleniyor...", fg="red", bg="#e1e1e1")
        self.info_label.pack(side=tk.RIGHT, padx=10)

        # --- GRAFİK ALANI ---
        self.plot_frame = tk.Frame(root)
        self.plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.root.after(100, self.harita_yukle)

    def harita_yukle(self):
        try:
            if os.path.exists(GRAPHML_FILE):
                self.info_label.config(text="Dosyadan yükleniyor...")
                self.root.update()
                self.G = ox.load_graphml(GRAPHML_FILE)
            else:
                self.info_label.config(text="İndiriliyor...")
                self.root.update()
                self.G = ox.graph_from_place(PLACE_NAME, network_type="drive")
                ox.save_graphml(self.G, filepath=GRAPHML_FILE)
            
            self.agirliklari_hesapla()
            self.info_label.config(text="Harita Hazır!", fg="green")
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def heuristic_dist(self, u, v):
        node_u = self.G.nodes[u]
        node_v = self.G.nodes[v]
        return ox.distance.great_circle(node_u['y'], node_u['x'], node_v['y'], node_v['x'])

    def agirliklari_hesapla(self):
        for u, v, k, data in self.G.edges(keys=True, data=True):
            length = data['length']
            road_type = data.get('highway', 'unclassified')
            if isinstance(road_type, list): road_type = road_type[0]
            
            if road_type in ['motorway', 'trunk']: factor = 10.0
            elif road_type in ['primary']: factor = 5.0
            elif road_type in ['secondary', 'tertiary']: factor = 1.5
            elif road_type in ['residential']: factor = 1.0
            else: factor = 2.0
            data['stress_cost'] = length * factor

    def get_route_length(self, route):
        total_dist = 0
        for u, v in zip(route[:-1], route[1:]):
            edge_data = self.G.get_edge_data(u, v)
            min_len = min([d['length'] for d in edge_data.values()])
            total_dist += min_len
        return total_dist

    def hesapla(self):
        if self.G is None: return
        start_name = self.start_combo.get()
        end_name = self.end_combo.get()

        if start_name == end_name:
            messagebox.showwarning("Uyarı", "Aynı noktalar seçilemez.")
            return

        self.info_label.config(text="Hesaplanıyor...", fg="blue")
        self.root.update()

        s_coords = LOCATIONS[start_name]
        e_coords = LOCATIONS[end_name]

        orig = ox.nearest_nodes(self.G, s_coords[1], s_coords[0])
        dest = ox.nearest_nodes(self.G, e_coords[1], e_coords[0])

        try:
            r_short = nx.astar_path(self.G, orig, dest, heuristic=self.heuristic_dist, weight="length")
            r_calm = nx.astar_path(self.G, orig, dest, heuristic=self.heuristic_dist, weight="stress_cost")
            
            l1 = self.get_route_length(r_short)
            l2 = self.get_route_length(r_calm)

            self.cizimi_guncelle(r_short, r_calm, l1, l2, s_coords, e_coords)
            self.info_label.config(text=f"Kırmızı: {l1:.0f}m | Mavi: {l2:.0f}m", fg="black")

        except nx.NetworkXNoPath:
            self.info_label.config(text="Yol Yok!", fg="red")

    def cizimi_guncelle(self, r1, r2, l1, l2, start_c, end_c):
        for widget in self.plot_frame.winfo_children():
            widget.destroy()

        fig, ax = ox.plot_graph_routes(
            self.G, [r1, r2], route_colors=['red', 'blue'],
            route_linewidth=4, node_size=0, bgcolor='white', show=False, close=False
        )

        ax.set_title(f"Hızlı: {l1:.0f}m (Kırmızı) vs Sakin: {l2:.0f}m (Mavi)", fontsize=10)
        ax.scatter(start_c[1], start_c[0], c='green', s=100, zorder=5)
        ax.scatter(end_c[1], end_c[0], c='black', s=100, zorder=5)

        # --- İNTERAKTİFLİK EKLEME ---
        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 1. Standart Toolbar (Opsiyonel olarak dursun)
        toolbar = NavigationToolbar2Tk(canvas, self.plot_frame)
        toolbar.update()
        
        # 2. Bizim Özel Kontrolcümüzü Devreye Alıyoruz (Zoom/Pan)
        self.zoom_pan_handler = HaritaKontrolcusu(ax, canvas)


if __name__ == "__main__":
    root = tk.Tk()
    app = RotaUygulamasi(root)
    root.mainloop()