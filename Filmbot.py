import logging
import os
import re
import sqlite3
import json
import asyncio
from sqlite3 import Error
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.environ.get("TOKEN")
DB_FILE = os.environ.get("DB_FILE", "List.db")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

if not TOKEN:
    raise ValueError("TOKEN tidak ditemukan di environment variables atau file .env")


def is_admin(user_id):
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        return conn
    except Error as e:
        logging.error(f"Database error: {e}")
        return None


def init_database():
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS films (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                )
            ''')
            cursor.execute("PRAGMA table_info(films)")
            columns = [row[1] for row in cursor.fetchall()]
            if "category" not in columns:
                cursor.execute("ALTER TABLE films ADD COLUMN category TEXT")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    series_title TEXT NOT NULL,
                    episode_number INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                )
            ''')
            cursor.execute("PRAGMA table_info(series)")
            columns_series = [row[1] for row in cursor.fetchall()]
            if "category" not in columns_series:
                cursor.execute("ALTER TABLE series ADD COLUMN category TEXT")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS command_stats (
                    command TEXT PRIMARY KEY,
                    usage_count INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS film_searches (
                    title TEXT PRIMARY KEY,
                    search_count INTEGER DEFAULT 0
                )
            ''')
            conn.commit()
            logging.info("Database initialized and synchronized successfully")
        except Error as e:
            logging.error(f"Database initialization error: {e}")
        finally:
            conn.close()
    else:
        logging.error("Cannot create database connection")


def record_command_usage(command_name):
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT usage_count FROM command_stats WHERE command = ?", (command_name,))
            row = cursor.fetchone()
            if row:
                cursor.execute("UPDATE command_stats SET usage_count = usage_count + 1 WHERE command = ?", (command_name,))
            else:
                cursor.execute("INSERT INTO command_stats (command, usage_count) VALUES (?, 1)", (command_name,))
            conn.commit()
        except Error as e:
            logging.error(e)
        finally:
            conn.close()


def record_film_search(search_title):
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT search_count FROM film_searches WHERE title = ?", (search_title,))
            row = cursor.fetchone()
            if row:
                cursor.execute("UPDATE film_searches SET search_count = search_count + 1 WHERE title = ?", (search_title,))
            else:
                cursor.execute("INSERT INTO film_searches (title, search_count) VALUES (?, 1)", (search_title,))
            conn.commit()
        except Error as e:
            logging.error(e)
        finally:
            conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("start")
    chat_id = update.effective_chat.id

    commands_message = (
        "Halo, selamat datang di Bot Media!\n\n"
        "Perintah yang tersedia:\n"
        "\u2022 /start - Menampilkan pesan sambutan dan daftar perintah\n"
        "\u2022 /film - Melihat daftar film\n"
        "\u2022 /series - Melihat daftar series\n"
        "\u2022 /kategori_film - Menampilkan kategori film\n"
        "\u2022 /kategori_series - Menampilkan kategori series\n"
        "\u2022 /hapus_film [judul] - Menghapus film (khusus admin)\n"
        "\u2022 /hapus_series [judul] - Menghapus series (khusus admin)\n"
        "\u2022 /stats - Melihat statistik penggunaan (khusus admin)\n"
        "\u2022 /buat_kategori <nama>.<tipe>.<judul> - Membuat kategori dan memasukkan judul\n"
        "\u2022 /masukan_kategori (nama). judul1, judul2 - Memasukkan judul ke kategori yang sudah ada\n"
    )

    if update.effective_chat.type in ["group", "supergroup"]:
        if is_admin(update.effective_user.id):
            admin_message = (
                "Halo Admin! Bot media telah aktif di grup ini.\n\n"
                "Perintah Admin:\n"
                "\u2022 /hapus_film [judul] - Menghapus film\n"
                "\u2022 /hapus_series [judul] - Menghapus series\n"
                "\u2022 /stats - Melihat statistik penggunaan\n"
                "\u2022 /buat_kategori <nama>.<tipe>.<judul> - Menambahkan kategori beserta daftar judul\n\n"
            )
            await update.message.reply_text(admin_message + commands_message)
        else:
            await update.message.reply_text(commands_message)
    else:
        await update.message.reply_text("Bot ini dirancang untuk digunakan di grup. Silakan tambahkan bot ini ke grup Anda.")


async def masukan_kategori_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        await update.message.reply_text(
            "Format salah.\nGunakan: /masukan_kategori (Nama Kategori). Judul 1, Judul 2, Judul 3, ..."
        )
        return

    params = args[1].strip()
    if '.' not in params:
        await update.message.reply_text(
            "Format salah. Pastikan menggunakan titik (.) sebagai pemisah antara kategori dan daftar judul."
        )
        return

    parts = params.split('.', 1)
    kategori = parts[0].strip()
    if kategori.startswith('(') and kategori.endswith(')'):
        kategori = kategori[1:-1].strip()

    judul_str = parts[1].strip()
    if not kategori or not judul_str:
        await update.message.reply_text("Kategori atau daftar judul tidak boleh kosong.")
        return

    judul_list = [j.strip() for j in judul_str.split(',') if j.strip()]
    if not judul_list:
        await update.message.reply_text("Daftar judul tidak valid.")
        return

    conn = create_connection()
    if conn is None:
        await update.message.reply_text("Tidak dapat terhubung ke database.")
        return

    updated_count = 0
    try:
        cursor = conn.cursor()
        for judul in judul_list:
            cursor.execute(
                "UPDATE films SET category = ? WHERE title LIKE ? COLLATE NOCASE",
                (kategori, f"%{judul}%")
            )
            updated_count += cursor.rowcount
            cursor.execute(
                "UPDATE series SET category = ? WHERE title LIKE ? COLLATE NOCASE",
                (kategori, f"%{judul}%")
            )
            updated_count += cursor.rowcount
        conn.commit()
    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan saat mengupdate kategori: {e}")
        conn.close()
        return
    conn.close()

    await update.message.reply_text(
        f"Kategori '{kategori}' telah diterapkan ke {updated_count} judul."
    )


async def film_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("film")
    args = context.args
    if args:
        search_title = " ".join(args)
        record_film_search(search_title)
        conn = create_connection()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT title, chat_id, message_id FROM films WHERE title LIKE ? COLLATE NOCASE",
                    (f"%{search_title}%",)
                )
                film = cursor.fetchone()
                if film:
                    await update.message.reply_text(f"Mengirimkan film: {film[0]}")
                    try:
                        await context.bot.forward_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=film[1],
                            message_id=film[2]
                        )
                    except Exception as e:
                        await update.message.reply_text(f"Gagal meneruskan film: {e}")
                else:
                    await update.message.reply_text(f"Film dengan judul '{search_title}' tidak ditemukan.")
            except Error as e:
                logging.error(f"Database error: {e}")
                await update.message.reply_text("Terjadi kesalahan saat mencari film.")
            finally:
                conn.close()
        else:
            await update.message.reply_text("Tidak dapat terhubung ke database.")
    else:
        await show_film_list(update.effective_chat.id, context, page=0)


SERIES_PER_PAGE = 10

async def series_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("series")
    args = context.args
    if args:
        search_title = " ".join(args)
        await show_series_episodes(update.effective_chat.id, search_title, context)
    else:
        await show_series_list(update.effective_chat.id, context, page=0)


async def show_series_list(chat_id, context, page=0):
    conn = create_connection()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT series_title) FROM series")
        total = cursor.fetchone()[0]
        if total == 0:
            await context.bot.send_message(chat_id, "Belum ada series yang tersimpan dalam database.")
            return

        cursor.execute("SELECT DISTINCT series_title FROM series ORDER BY series_title LIMIT ? OFFSET ?",
                       (SERIES_PER_PAGE, page * SERIES_PER_PAGE))
        series = cursor.fetchall()
        total_pages = (total + SERIES_PER_PAGE - 1) // SERIES_PER_PAGE

        keyboard = []
        for s in series:
            title = s[0][:35]
            keyboard.append([InlineKeyboardButton(title, callback_data=f"sel_series_{s[0]}")])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅", callback_data=f"series_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡", callback_data=f"series_page_{page+1}"))
        if nav:
            keyboard.append(nav)

        await context.bot.send_message(
            chat_id, "\U0001f4fa *DAFTAR SERIES*\nPilih series:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    except Error as e:
        logging.error(f"Database error: {e}")
    finally:
        conn.close()


async def show_series_episodes(chat_id, series_title, context, callback_query=None):
    conn = create_connection()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, series_title, episode_number FROM series WHERE series_title LIKE ? COLLATE NOCASE ORDER BY episode_number",
            (f"%{series_title}%",)
        )
        episodes = cursor.fetchall()
        if not episodes:
            msg = f"Series '{series_title}' tidak ditemukan."
            if callback_query:
                await callback_query.edit_message_text(msg)
            else:
                await context.bot.send_message(chat_id, msg)
            return

        series_name = episodes[0][2]
        keyboard = []
        for i, ep in enumerate(episodes, 1):
            if (i - 1) % 3 == 0:
                keyboard.append([])
            keyboard[-1].append(InlineKeyboardButton(f"Eps {ep[3]}", callback_data=f"episode_{ep[0]}"))
        keyboard.append([InlineKeyboardButton("← Daftar Series", callback_data="back_series")])

        text = f"*{series_name}*\nPilih episode:"
        if callback_query:
            await callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except Error as e:
        logging.error(f"Database error: {e}")
    finally:
        conn.close()


FILM_PER_PAGE = 10

async def show_film_list(chat_id, context, page=0):
    conn = create_connection()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM films")
        total = cursor.fetchone()[0]
        if total == 0:
            await context.bot.send_message(chat_id, "Belum ada film yang tersimpan dalam database.")
            return

        cursor.execute("SELECT id, title FROM films ORDER BY title LIMIT ? OFFSET ?",
                       (FILM_PER_PAGE, page * FILM_PER_PAGE))
        films = cursor.fetchall()
        total_pages = (total + FILM_PER_PAGE - 1) // FILM_PER_PAGE

        keyboard = []
        for f in films:
            title = f[1][:35]
            keyboard.append([InlineKeyboardButton(title, callback_data=f"sel_film_{f[0]}")])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅", callback_data=f"film_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡", callback_data=f"film_page_{page+1}"))
        if nav:
            keyboard.append(nav)

        await context.bot.send_message(
            chat_id, "\U0001f3ac *DAFTAR FILM*\nPilih film:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    except Error as e:
        logging.error(f"Database error: {e}")
    finally:
        conn.close()


async def show_film_list_paginated(query, page=0):
    conn = create_connection()
    if conn is None:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM films")
        total = cursor.fetchone()[0]
        if total == 0:
            await query.edit_message_text("Belum ada film yang tersimpan dalam database.")
            return

        cursor.execute("SELECT id, title FROM films ORDER BY title LIMIT ? OFFSET ?",
                       (FILM_PER_PAGE, page * FILM_PER_PAGE))
        films = cursor.fetchall()
        total_pages = (total + FILM_PER_PAGE - 1) // FILM_PER_PAGE

        keyboard = []
        for f in films:
            title = f[1][:35]
            keyboard.append([InlineKeyboardButton(title, callback_data=f"sel_film_{f[0]}")])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅", callback_data=f"film_page_{page-1}"))
        nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡", callback_data=f"film_page_{page+1}"))
        if nav:
            keyboard.append(nav)

        await query.edit_message_text(
            "\U0001f3ac *DAFTAR FILM*\nPilih film:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
        )
    except Error as e:
        logging.error(e)
    finally:
        conn.close()


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data.startswith("sel_film_"):
        film_id = int(data.split("_")[2])
        conn = create_connection()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT title, chat_id, message_id FROM films WHERE id = ?", (film_id,))
                film = cursor.fetchone()
                if film:
                    await query.edit_message_text(f"Mengirimkan film: {film[0]}")
                    try:
                        await context.bot.forward_message(
                            chat_id=query.message.chat_id,
                            from_chat_id=film[1],
                            message_id=film[2]
                        )
                    except Exception as e:
                        await query.message.reply_text(f"Gagal meneruskan film: {e}")
                else:
                    await query.edit_message_text("Film tidak ditemukan.")
            except Error as e:
                logging.error(e)
            finally:
                conn.close()
        return

    if data.startswith("film_page_"):
        page = int(data.split("_")[2])
        await show_film_list_paginated(query, page)
        return

    if data == "back_film":
        await show_film_list_paginated(query, 0)
        return

    if data.startswith("sel_series_"):
        series_title = data[11:]
        await show_series_episodes(query.message.chat_id, series_title, context, callback_query=query)

    elif data.startswith("series_page_"):
        page = int(data.split("_")[2])
        conn = create_connection()
        if conn is None:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT series_title) FROM series")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT DISTINCT series_title FROM series ORDER BY series_title LIMIT ? OFFSET ?",
                           (SERIES_PER_PAGE, page * SERIES_PER_PAGE))
            series = cursor.fetchall()
            total_pages = (total + SERIES_PER_PAGE - 1) // SERIES_PER_PAGE

            keyboard = []
            for s in series:
                title = s[0][:35]
                keyboard.append([InlineKeyboardButton(title, callback_data=f"sel_series_{s[0]}")])
            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅", callback_data=f"series_page_{page-1}"))
            nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton("➡", callback_data=f"series_page_{page+1}"))
            if nav:
                keyboard.append(nav)

            await query.edit_message_text(
                "\U0001f4fa *DAFTAR SERIES*\nPilih series:",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
        except Error as e:
            logging.error(e)
        finally:
            conn.close()

    elif data == "back_series":
        await query.edit_message_text("Memuat daftar series...")
        conn = create_connection()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT series_title) FROM series")
                total = cursor.fetchone()[0]
                cursor.execute("SELECT DISTINCT series_title FROM series ORDER BY series_title LIMIT ? OFFSET 0",
                               (SERIES_PER_PAGE,))
                series = cursor.fetchall()
                total_pages = (total + SERIES_PER_PAGE - 1) // SERIES_PER_PAGE

                keyboard = []
                for s in series:
                    title = s[0][:35]
                    keyboard.append([InlineKeyboardButton(title, callback_data=f"sel_series_{s[0]}")])
                nav = []
                nav.append(InlineKeyboardButton(f"1/{total_pages}", callback_data="noop"))
                if total_pages > 1:
                    nav.append(InlineKeyboardButton("➡", callback_data="series_page_1"))
                if nav:
                    keyboard.append(nav)

                await query.edit_message_text(
                    "\U0001f4fa *DAFTAR SERIES*\nPilih series:",
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
                )
            except Error as e:
                logging.error(e)
            finally:
                conn.close()

    elif data.startswith("episode_"):
        episode_id = data.split("_")[1]
        conn = create_connection()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT title, series_title, episode_number, chat_id, message_id FROM series WHERE id = ?",
                    (episode_id,)
                )
                episode = cursor.fetchone()
                if episode:
                    title, series_title, episode_number, chat_id, message_id = episode
                    await query.message.reply_text(f"Mengirimkan Episode {episode_number} dari {series_title}: {title}")
                    try:
                        await context.bot.forward_message(
                            chat_id=query.message.chat_id,
                            from_chat_id=chat_id,
                            message_id=message_id
                        )
                    except Exception as e:
                        await query.message.reply_text(f"Gagal meneruskan episode: {e}")
                else:
                    await query.message.reply_text("Episode tidak ditemukan.")
            except Error as e:
                logging.error(e)
                await query.message.reply_text("Terjadi kesalahan saat mengakses database.")
            finally:
                conn.close()
        else:
            await query.message.reply_text("Tidak dapat terhubung ke database.")


async def create_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("buat_kategori")
    args = update.message.text.split(None, 1)
    if len(args) < 2:
        await update.message.reply_text("Format salah. Gunakan:\n/buat_kategori <nama kategori>.<tipe>.<judul 1>, <judul 2>, ...")
        return
    parts = args[1].split('.')
    if len(parts) < 3:
        await update.message.reply_text("Format salah. Pastikan input memiliki tiga bagian: nama kategori, tipe (film/series), dan daftar judul.")
        return
    category_name = parts[0].strip()
    media_type = parts[1].strip().lower()
    titles = [t.strip() for t in parts[2].split(',') if t.strip()]
    if media_type not in ["film", "series"]:
        await update.message.reply_text("Tipe harus 'film' atau 'series'.")
        return
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            updated_count = 0
            for title in titles:
                if media_type == "film":
                    cursor.execute(
                        "UPDATE films SET category = ? WHERE title LIKE ? COLLATE NOCASE",
                        (category_name, f"%{title}%")
                    )
                else:
                    cursor.execute(
                        "UPDATE series SET category = ? WHERE title LIKE ? COLLATE NOCASE",
                        (category_name, f"%{title}%")
                    )
                updated_count += cursor.rowcount
            conn.commit()
            await update.message.reply_text(f"Kategori '{category_name}' diterapkan ke {updated_count} judul {media_type}.")
        except Error as e:
            logging.error(e)
            await update.message.reply_text("Terjadi kesalahan saat membuat kategori.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def list_film_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("kategori_film")
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, GROUP_CONCAT(title, ', ')
                FROM films
                WHERE category IS NOT NULL
                GROUP BY category
            """)
            rows = cursor.fetchall()
            if not rows:
                await update.message.reply_text("Belum ada kategori film yang terdaftar.")
                return
            msg = ""
            for row in rows:
                msg += f"*{row[0]}*\n{row[1]}\n\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Error as e:
            logging.error(e)
            await update.message.reply_text("Terjadi kesalahan saat mengambil kategori film.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def list_series_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("kategori_series")
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT category, GROUP_CONCAT(title, ', ')
                FROM series
                WHERE category IS NOT NULL
                GROUP BY category
            """)
            rows = cursor.fetchall()
            if not rows:
                await update.message.reply_text("Belum ada kategori series yang terdaftar.")
                return
            msg = ""
            for row in rows:
                msg += f"*{row[0]}*\n{row[1]}\n\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Error as e:
            logging.error(e)
            await update.message.reply_text("Terjadi kesalahan saat mengambil kategori series.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def delete_film_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("hapus_film")
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Hanya admin yang dapat menghapus film!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Silakan berikan judul film yang ingin dihapus. Contoh: /hapus_film [judul film]")
        return
    title = " ".join(args)
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM films WHERE title = ?", (title,))
            if cursor.rowcount > 0:
                conn.commit()
                await update.message.reply_text(f"Film '{title}' telah dihapus dari database!")
            else:
                await update.message.reply_text(f"Film dengan judul '{title}' tidak ditemukan.")
        except Error as e:
            logging.error(f"Database error while deleting film: {e}")
            await update.message.reply_text("Terjadi kesalahan saat menghapus film.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def delete_series_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("hapus_series")
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Hanya admin yang dapat menghapus series!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Silakan berikan judul series yang ingin dihapus. Contoh: /hapus_series [judul series]")
        return
    series_title = " ".join(args)
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM series WHERE series_title = ?", (series_title,))
            if cursor.rowcount > 0:
                conn.commit()
                await update.message.reply_text(f"Series '{series_title}' telah dihapus dari database!")
            else:
                await update.message.reply_text(f"Series dengan judul '{series_title}' tidak ditemukan.")
        except Error as e:
            logging.error(f"Database error while deleting series: {e}")
            await update.message.reply_text("Terjadi kesalahan saat menghapus series.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_command_usage("stats")
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Hanya admin yang dapat melihat stats!")
        return
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT command, usage_count FROM command_stats")
            commands = cursor.fetchall()
            cursor.execute("SELECT title, search_count FROM film_searches")
            searches = cursor.fetchall()
            msg = "*Stats Penggunaan Bot:*\n\n*Perintah:*\n"
            for cmd, count in commands:
                msg += f"{cmd}: {count}\n"
            msg += "\n*Pencarian Film:*\n"
            for title, count in searches:
                msg += f"{title}: {count}\n"
            await update.message.reply_text(msg, parse_mode="Markdown")
        except Error as e:
            logging.error(e)
            await update.message.reply_text("Terjadi kesalahan saat mengambil stats.")
        finally:
            conn.close()
    else:
        await update.message.reply_text("Tidak dapat terhubung ke database.")


async def tambah_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Hanya admin yang bisa menggunakan perintah ini!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply pesan video/film yang ingin ditambahkan dengan perintah ini.")
        return
    msg = update.message.reply_to_message
    if not any([msg.video, msg.document, msg.photo]):
        await update.message.reply_text("Pesan yang di-reply bukan video/gambar.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Gunakan:\n/tambah [judul]\n/tambah [judul] EP [nomor]")
        return
    caption = " ".join(args)
    series_match = re.match(r'(.+?)\s+(?:EP|Episode|Ep)\s*(\d+)(.*)', caption, re.IGNORECASE)
    if series_match:
        series_title = series_match.group(1).strip()
        episode_number = int(series_match.group(2))
        suffix = series_match.group(3).strip()
        episode_title = f"Episode {episode_number} {suffix}".strip() if suffix else f"Episode {episode_number}"
        save_series_episode(episode_title, series_title, episode_number, msg.chat_id, msg.message_id)
        await update.message.reply_text(f"Episode {episode_number} dari series '{series_title}' berhasil ditambahkan!")
    else:
        save_film(caption, msg.chat_id, msg.message_id)
        await update.message.reply_text(f"Film '{caption}' berhasil ditambahkan!")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.caption:
        return
    caption = message.caption.strip()
    is_media = any([message.video, message.document, message.photo])
    if not is_media:
        return
    if caption.startswith("FILM:"):
        title = caption[5:].strip()
        save_film(title, message.chat_id, message.message_id)
        await message.reply_text(f"Film '{title}' berhasil disimpan!")
    elif caption.startswith("SERIES:"):
        try:
            match = re.match(r"SERIES:\s*(.+?)\s*-\s*Episode\s*(\d+)", caption)
            if match:
                series_title = match.group(1).strip()
                episode_number = int(match.group(2))
                episode_title = f"Episode {episode_number}"
                save_series_episode(episode_title, series_title, episode_number, message.chat_id, message.message_id)
                await message.reply_text(f"Episode {episode_number} dari series '{series_title}' berhasil disimpan!")
            else:
                await message.reply_text("Format caption salah! Gunakan: SERIES: [judul series] - Episode [nomor]")
        except Exception as e:
            logging.error(f"Error processing series caption: {e}")
            await message.reply_text("Terjadi kesalahan saat memproses caption series.")
    else:
        series_match = re.match(r'(.+?)\s+(?:EP|Episode|Ep)\s*(\d+)(.*)', caption, re.IGNORECASE)
        if series_match:
            series_title = series_match.group(1).strip()
            episode_number = int(series_match.group(2))
            suffix = series_match.group(3).strip()
            episode_title = f"Episode {episode_number} {suffix}".strip() if suffix else f"Episode {episode_number}"
            save_series_episode(episode_title, series_title, episode_number, message.chat_id, message.message_id)
            await message.reply_text(f"Episode {episode_number} dari series '{series_title}' berhasil disimpan!")
        else:
            save_film(caption, message.chat_id, message.message_id)
            await message.reply_text(f"Film '{caption}' berhasil disimpan!")


def scan_updates(updates):
    found = 0
    series_found = 0
    film_found = 0
    for upd in updates:
        msg = upd.message
        if not msg or not msg.caption:
            continue
        if not any([msg.video, msg.document, msg.photo]):
            continue
        caption = msg.caption.strip()
        series_match = re.match(r'(.+?)\s+(?:EP|Episode|Ep)\s*(\d+)(.*)', caption, re.IGNORECASE)
        if series_match:
            series_title = series_match.group(1).strip()
            episode_number = int(series_match.group(2))
            suffix = series_match.group(3).strip()
            episode_title = f"Episode {episode_number} {suffix}".strip() if suffix else f"Episode {episode_number}"
            save_series_episode(episode_title, series_title, episode_number, msg.chat_id, msg.message_id)
            series_found += 1
        else:
            save_film(caption, msg.chat_id, msg.message_id)
            film_found += 1
        found += 1
    return found, film_found, series_found


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Hanya admin yang bisa menggunakan perintah ini!")
        return
    await update.message.reply_text("Memulai scan grup...")
    try:
        updates = await context.bot.get_updates(allowed_updates=["message"])
    except Exception as e:
        await update.message.reply_text(f"Gagal mendapatkan updates: {e}")
        return
    found, film_found, series_found = scan_updates(updates)
    if found > 0:
        await update.message.reply_text(
            f"Scan selesai!\nDitemukan: {found} file\n- Film: {film_found}\n- Series: {series_found}"
        )
    else:
        await update.message.reply_text("Tidak ada file video ditemukan di pesan terbaru.")


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member.new_chat_member.status == "member":
        chat = update.effective_chat
        await context.bot.send_message(
            chat_id=chat.id,
            text="Halo! Saya akan scan pesan terbaru untuk mencari file video..."
        )
        try:
            updates = await context.bot.get_updates(allowed_updates=["message"])
        except Exception as e:
            logging.error(f"Scan on join failed: {e}")
            return
        found, film_found, series_found = scan_updates(updates)
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"Scan selesai! Ditemukan {found} file video (Film: {film_found}, Series: {series_found})."
        )


def save_film(title, chat_id, message_id, category=None):
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM films WHERE title = ?", (title,))
            existing_film = cursor.fetchone()
            if existing_film:
                cursor.execute(
                    "UPDATE films SET chat_id = ?, message_id = ?, category = ? WHERE title = ?",
                    (chat_id, message_id, category, title)
                )
            else:
                cursor.execute(
                    "INSERT INTO films (title, chat_id, message_id, category) VALUES (?, ?, ?, ?)",
                    (title, chat_id, message_id, category)
                )
            conn.commit()
        except Error as e:
            logging.error(f"Database error while saving film: {e}")
        finally:
            conn.close()
    else:
        logging.error("Cannot create database connection")


def save_series_episode(title, series_title, episode_number, chat_id, message_id, category=None):
    conn = create_connection()
    if conn is not None:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM series WHERE series_title = ? AND episode_number = ?",
                (series_title, episode_number)
            )
            existing_episode = cursor.fetchone()
            if existing_episode:
                cursor.execute(
                    "UPDATE series SET title = ?, chat_id = ?, message_id = ?, category = ? WHERE series_title = ? AND episode_number = ?",
                    (title, chat_id, message_id, category, series_title, episode_number)
                )
            else:
                cursor.execute(
                    "INSERT INTO series (title, series_title, episode_number, chat_id, message_id, category) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, series_title, episode_number, chat_id, message_id, category)
                )
            conn.commit()
        except Error as e:
            logging.error(f"Database error while saving series episode: {e}")
        finally:
            conn.close()
    else:
        logging.error("Cannot create database connection")


def setup_webhook(app):
    init_database()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("film", film_command))
    app.add_handler(CommandHandler("series", series_command))
    app.add_handler(CommandHandler("buat_kategori", create_category))
    app.add_handler(CommandHandler("masukan_kategori", masukan_kategori_command))
    app.add_handler(CommandHandler("kategori_film", list_film_categories))
    app.add_handler(CommandHandler("kategori_series", list_series_categories))
    app.add_handler(CommandHandler("hapus_film", delete_film_command))
    app.add_handler(CommandHandler("hapus_series", delete_series_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("tambah", tambah_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_media))
    return app


application = Application.builder().token(TOKEN).updater(None).build()
setup_webhook(application)
asyncio.run(application.initialize())


