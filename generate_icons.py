#!/usr/bin/env python3
# pylint: disable=bare-except,too-many-locals,too-many-statements
"""
Icon-Generator für PWA
Generiert alle benötigten Icon-Größen aus einem einzigen Source-Icon

Benötigt: pip install Pillow

Verwendung:
    python generate_icons.py source_icon.png
"""

import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ Pillow nicht installiert!")
    print("Installation: pip install Pillow")
    sys.exit(1)

# Icon-Größen für PWA
ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

# Zusätzliche iOS-Größen
IOS_SIZES = [120, 152, 167, 180]

# Favicon-Größen
FAVICON_SIZES = [16, 32, 48]


def create_default_icon(size, output_path):
    """Erstellt ein Standard-Icon mit Buchstabe 'R' für Rechnungen"""
    # Erstelle quadratisches Icon mit blauem Hintergrund
    img = Image.new("RGB", (size, size), color="#0d6efd")
    draw = ImageDraw.Draw(img)

    # Versuche Font zu laden, sonst Default
    try:
        # Größere Schrift für bessere Lesbarkeit
        font_size = int(size * 0.6)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        font = ImageFont.load_default()

    # Zeichne 'R' in der Mitte
    text = "R"

    # Zentriere Text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (size - text_width) / 2
    y = (size - text_height) / 2 - bbox[1]  # Kompensiere bbox-Offset

    draw.text((x, y), text, fill="white", font=font)

    # Speichere als PNG
    img.save(output_path, "PNG", optimize=True)
    print(f"✅ Erstellt: {output_path} ({size}x{size})")


def generate_icons(source_icon=None):
    """Generiert alle benötigten Icons"""
    icons_dir = Path("static/icons")
    icons_dir.mkdir(parents=True, exist_ok=True)

    if source_icon and os.path.exists(source_icon):
        print(f"📸 Verwende Source-Icon: {source_icon}")
        source_img = Image.open(source_icon)

        # Konvertiere zu RGBA falls nötig
        if source_img.mode != "RGBA":
            source_img = source_img.convert("RGBA")
    else:
        print("ℹ️  Kein Source-Icon gefunden - generiere Standard-Icons")
        source_img = None

    # PWA Icons
    print("\n📱 Generiere PWA-Icons...")
    for size in ICON_SIZES:
        output_path = icons_dir / f"icon-{size}x{size}.png"

        if source_img:
            # Resize mit hoher Qualität
            resized = source_img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(output_path, "PNG", optimize=True)
            print(f"✅ {output_path} ({size}x{size})")
        else:
            create_default_icon(size, output_path)

    # iOS Icons
    print("\n🍎 Generiere iOS Touch Icons...")
    for size in IOS_SIZES:
        output_path = icons_dir / f"apple-touch-icon-{size}x{size}.png"

        if source_img:
            resized = source_img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(output_path, "PNG", optimize=True)
            print(f"✅ {output_path} ({size}x{size})")
        else:
            create_default_icon(size, output_path)

    # Standard Apple Touch Icon (180x180)
    if source_img:
        apple_icon = source_img.resize((180, 180), Image.Resampling.LANCZOS)
        apple_icon.save(icons_dir / "apple-touch-icon.png", "PNG", optimize=True)
    else:
        create_default_icon(180, icons_dir / "apple-touch-icon.png")

    print("✅ apple-touch-icon.png (180x180)")

    # Favicons
    print("\n🔖 Generiere Favicons...")
    for size in FAVICON_SIZES:
        output_path = icons_dir / f"favicon-{size}x{size}.png"

        if source_img:
            resized = source_img.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(output_path, "PNG", optimize=True)
            print(f"✅ {output_path} ({size}x{size})")
        else:
            create_default_icon(size, output_path)

    # Standard favicon.ico (multi-size)
    print("\n🔖 Erstelle favicon.ico...")
    favicon_sizes = [(16, 16), (32, 32), (48, 48)]
    favicon_images = []

    for size in favicon_sizes:
        if source_img:
            resized = source_img.resize(size, Image.Resampling.LANCZOS)
            favicon_images.append(resized)
        else:
            # Erstelle temporäres Image
            temp_img = Image.new("RGB", size, color="#0d6efd")
            draw = ImageDraw.Draw(temp_img)
            try:
                font_size = int(size[0] * 0.6)
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), "R", font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (size[0] - text_width) / 2
            y = (size[1] - text_height) / 2 - bbox[1]
            draw.text((x, y), "R", fill="white", font=font)
            favicon_images.append(temp_img)

    # Speichere als .ico
    favicon_path = Path("static") / "favicon.ico"
    favicon_images[0].save(
        favicon_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in favicon_images],
        append_images=favicon_images[1:],
    )
    print(f"✅ {favicon_path} (multi-size)")

    # Maskable Icons (für Android)
    print("\n🤖 Generiere Maskable Icons...")
    for size in [192, 512]:
        output_path = icons_dir / f"icon-maskable-{size}x{size}.png"

        if source_img:
            # Maskable Icon mit Safe-Zone (80% des Contents)
            canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))

            # Content ist 80% der Größe
            content_size = int(size * 0.8)
            content_img = source_img.resize((content_size, content_size), Image.Resampling.LANCZOS)

            # Zentriere Content
            offset = (size - content_size) // 2
            canvas.paste(content_img, (offset, offset), content_img)

            canvas.save(output_path, "PNG", optimize=True)
            print(f"✅ {output_path} ({size}x{size})")
        else:
            create_default_icon(size, output_path)

    # Shortcut Icons
    print("\n⚡ Generiere Shortcut Icons...")
    shortcut_icons = {
        "shortcut-new.png": ("📝", "#28a745"),
        "shortcut-list.png": ("📋", "#0d6efd"),
        "shortcut-customers.png": ("👥", "#6f42c1"),
    }

    for filename, (emoji, color) in shortcut_icons.items():
        output_path = icons_dir / filename
        size = 96

        img = Image.new("RGB", (size, size), color=color)
        draw = ImageDraw.Draw(img)

        try:
            font_size = int(size * 0.5)
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", font_size)
        except:
            # Fallback: Text statt Emoji
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), emoji, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size - text_width) / 2
        y = (size - text_height) / 2 - bbox[1]

        draw.text((x, y), emoji, fill="white", font=font)
        img.save(output_path, "PNG", optimize=True)
        print(f"✅ {output_path} ({size}x{size})")

    print("\n✅ Alle Icons erfolgreich generiert!")
    print(f"📁 Ausgabe: {icons_dir.absolute()}")
    print("\nℹ️  Hinweis: Für bessere Icons, führe aus:")
    print("   python generate_icons.py /pfad/zu/deinem/logo.png")


if __name__ == "__main__":
    source = sys.argv[1] if len(sys.argv) > 1 else None
    generate_icons(source)
