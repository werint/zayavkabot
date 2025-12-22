import os
import discord
from discord.ext import commands
from discord import app_commands
import json
import re
from datetime import datetime
import traceback
import sys
import asyncpg
import asyncio

# Получаем данные из переменных окружения Railway
TOKEN = os.environ.get('DISCORD_TOKEN')
if not TOKEN:
    print("❌ ОШИБКА: Переменная окружения DISCORD_TOKEN не установлена!")
    sys.exit(1)

# Данные для PostgreSQL (Railway предоставляет DATABASE_URL)
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("❌ ОШИБКА: Переменная окружения DATABASE_URL не установлена!")
    sys.exit(1)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ID каналов для основного сервера
LOGS_CHANNEL_ID = 1317565432210915379  # Канал для логов
APPLICATIONS_CATEGORY_ID = 1316900282340347934  # Категория для заявок

# ID ролей для тега и административных прав
TAG_ROLE_IDS = [
    1223589384452833290,
    1310673963000528949,
    1381682246678741022,
    1381685630555258931,
    1381683377090068550
]

# ID ролей для использования slash-команд (только эти две роли)
SLASH_COMMAND_ROLE_IDS = [1310673963000528949, 1381685630555258931]

# URL изображений для заявки
IMAGE_URL = "https://media.discordapp.net/attachments/1189879069991510066/1449528629775302698/zastavki-gas-kvas-com-n1e0-p-zastavki-na-telefon-am-nyam-2.png?ex=694285fc&is=6941347c&hm=560b40c38fbc83ae9821b60df73fadefb0d917eb0082f53635350b686b33b605&=&format=webp&quality=lossless"
SMALL_ICON_URL = "https://cdn.discordapp.com/attachments/1381981605848944720/1449946500057792543/4.png?ex=6940bf68&is=693f6de8&hm=df622f91cff0f82216929fb398fbc04aea2ab256c4323a18840538c0bbdabb08&"

# Глобальный пул подключений к БД
db_pool = None

# Функция проверки прав для slash-команд
def has_slash_command_permission(interaction: discord.Interaction):
    """Проверяет, есть ли у пользователя права на использование slash-команд"""
    try:
        for role_id in SLASH_COMMAND_ROLE_IDS:
            role = discord.utils.get(interaction.user.roles, id=role_id)
            if role:
                return True
        return False
    except Exception as e:
        print(f"Ошибка проверки прав для slash-команд: {e}")
        return False

class Application:
    def __init__(self, username_static, ooc_info, fam_history, reason, rollbacks, discord_user, discord_id, 
                 message_id=None, status="pending", channel_id=None, moderator=None, reason_reject=None,
                 created_at=None, updated_at=None, id=None):
        self.id = id
        self.username_static = username_static
        self.ooc_info = ooc_info
        self.fam_history = fam_history
        self.reason = reason
        self.rollbacks = rollbacks
        self.discord_user = discord_user
        self.discord_id = discord_id
        self.message_id = message_id
        self.status = status
        self.channel_id = channel_id
        self.moderator = moderator
        self.reason_reject = reason_reject
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        return {
            "id": self.id,
            "username_static": self.username_static,
            "ooc_info": self.ooc_info,
            "fam_history": self.fam_history,
            "reason": self.reason,
            "rollbacks": self.rollbacks,
            "discord_user": self.discord_user,
            "discord_id": self.discord_id,
            "message_id": self.message_id,
            "status": self.status,
            "channel_id": self.channel_id,
            "moderator": self.moderator,
            "reason_reject": self.reason_reject,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at
        }

    @classmethod
    def from_dict(cls, data):
        app = cls(
            id=data.get("id"),
            username_static=data["username_static"],
            ooc_info=data["ooc_info"],
            fam_history=data["fam_history"],
            reason=data["reason"],
            rollbacks=data["rollbacks"],
            discord_user=data["discord_user"],
            discord_id=data["discord_id"],
            message_id=str(data.get("message_id")) if data.get("message_id") else None,  # Преобразуем
            status=data.get("status", "pending"),
            channel_id=str(data.get("channel_id")) if data.get("channel_id") else None,  # Преобразуем
            moderator=data.get("moderator"),
            reason_reject=data.get("reason_reject"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now()
        )
        return app

async def init_database():
    """Подключение к существующей базе данных (без создания таблиц)"""
    global db_pool
    try:
        # Создаем пул подключений
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        print("✅ Подключение к PostgreSQL установлено")
        
        async with db_pool.acquire() as conn:
            # Простая проверка подключения - проверяем существование таблицы
            try:
                await conn.fetchval("SELECT COUNT(*) FROM applications LIMIT 1")
                print("✅ Таблица applications найдена")
            except Exception as e:
                print(f"❌ Таблица applications не найдена: {e}")
                raise Exception("Таблица applications должна быть создана заранее")
            
    except Exception as e:
        print(f"❌ Ошибка при подключении к базе данных: {e}")
        traceback.print_exc()
        raise

async def save_application(application):
    """Сохраняет заявку в базу данных"""
    try:
        async with db_pool.acquire() as conn:
            if application.id:
                await conn.execute('''
                    UPDATE applications SET
                        username_static = $1,
                        ooc_info = $2,
                        fam_history = $3,
                        reason = $4,
                        rollbacks = $5,
                        discord_user = $6,
                        discord_id = $7,
                        message_id = $8,
                        status = $9,
                        channel_id = $10,
                        moderator = $11,
                        reason_reject = $12,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $13
                ''', 
                application.username_static, application.ooc_info, application.fam_history,
                application.reason, application.rollbacks, application.discord_user,
                application.discord_id, 
                str(application.message_id) if application.message_id else None,
                application.status,
                str(application.channel_id) if application.channel_id else None,
                application.moderator, application.reason_reject,
                application.id)
            else:
                record = await conn.fetchrow('''
                    INSERT INTO applications 
                    (username_static, ooc_info, fam_history, reason, rollbacks, discord_user, 
                     discord_id, message_id, status, channel_id, moderator, reason_reject)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    RETURNING id, created_at, updated_at
                ''',
                application.username_static, application.ooc_info, application.fam_history,
                application.reason, application.rollbacks, application.discord_user,
                application.discord_id, 
                str(application.message_id) if application.message_id else None,
                application.status,
                str(application.channel_id) if application.channel_id else None,
                application.moderator, application.reason_reject)
                
                if record:
                    application.id = record['id']
                    application.created_at = record['created_at']
                    application.updated_at = record['updated_at']
                    
        print(f"✅ Заявка сохранена в БД (ID: {application.id})")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения заявки: {e}")
        traceback.print_exc()
        return False

async def load_applications():
    """Загружает все заявки из базы данных"""
    try:
        applications_list = []
        async with db_pool.acquire() as conn:
            records = await conn.fetch('''
                SELECT * FROM applications ORDER BY created_at DESC
            ''')
            
            for record in records:
                app = Application(
                    id=record['id'],
                    username_static=record['username_static'],
                    ooc_info=record['ooc_info'],
                    fam_history=record['fam_history'],
                    reason=record['reason'],
                    rollbacks=record['rollbacks'],
                    discord_user=record['discord_user'],
                    discord_id=record['discord_id'],
                    message_id=record['message_id'],
                    status=record['status'],
                    channel_id=record['channel_id'],
                    moderator=record['moderator'],
                    reason_reject=record['reason_reject'],
                    created_at=record['created_at'],
                    updated_at=record['updated_at']
                )
                applications_list.append(app)
        
        print(f"✅ Загружено {len(applications_list)} заявок из БД")
        return applications_list
    except Exception as e:
        print(f"❌ Ошибка загрузки заявок: {e}")
        traceback.print_exc()
        return []

async def get_user_applications(discord_id):
    """Получает заявки пользователя по discord_id"""
    try:
        applications_list = []
        async with db_pool.acquire() as conn:
            records = await conn.fetch('''
                SELECT * FROM applications 
                WHERE discord_id = $1 
                ORDER BY created_at DESC
            ''', discord_id)
            
            for record in records:
                app = Application(
                    id=record['id'],
                    username_static=record['username_static'],
                    ooc_info=record['ooc_info'],
                    fam_history=record['fam_history'],
                    reason=record['reason'],
                    rollbacks=record['rollbacks'],
                    discord_user=record['discord_user'],
                    discord_id=record['discord_id'],
                    message_id=record['message_id'],
                    status=record['status'],
                    channel_id=record['channel_id'],
                    moderator=record['moderator'],
                    reason_reject=record['reason_reject'],
                    created_at=record['created_at'],
                    updated_at=record['updated_at']
                )
                applications_list.append(app)
        
        return applications_list
    except Exception as e:
        print(f"❌ Ошибка получения заявок пользователя: {e}")
        return []

async def get_pending_applications():
    """Получает все заявки со статусом pending"""
    try:
        applications_list = []
        async with db_pool.acquire() as conn:
            records = await conn.fetch('''
                SELECT * FROM applications 
                WHERE status = 'pending'
                ORDER BY created_at DESC
            ''')
            
            for record in records:
                app = Application(
                    id=record['id'],
                    username_static=record['username_static'],
                    ooc_info=record['ooc_info'],
                    fam_history=record['fam_history'],
                    reason=record['reason'],
                    rollbacks=record['rollbacks'],
                    discord_user=record['discord_user'],
                    discord_id=record['discord_id'],
                    message_id=record['message_id'],
                    status=record['status'],
                    channel_id=record['channel_id'],
                    moderator=record['moderator'],
                    reason_reject=record['reason_reject'],
                    created_at=record['created_at'],
                    updated_at=record['updated_at']
                )
                applications_list.append(app)
        
        return applications_list
    except Exception as e:
        print(f"❌ Ошибка получения pending заявок: {e}")
        return []

async def get_application_by_id(app_id):
    """Получает заявку по ID"""
    try:
        async with db_pool.acquire() as conn:
            record = await conn.fetchrow('''
                SELECT * FROM applications WHERE id = $1
            ''', app_id)
            
            if record:
                app = Application(
                    id=record['id'],
                    username_static=record['username_static'],
                    ooc_info=record['ooc_info'],
                    fam_history=record['fam_history'],
                    reason=record['reason'],
                    rollbacks=record['rollbacks'],
                    discord_user=record['discord_user'],
                    discord_id=record['discord_id'],
                    message_id=record['message_id'],
                    status=record['status'],
                    channel_id=record['channel_id'],
                    moderator=record['moderator'],
                    reason_reject=record['reason_reject'],
                    created_at=record['created_at'],
                    updated_at=record['updated_at']
                )
                return app
        return None
    except Exception as e:
        print(f"❌ Ошибка получения заявки по ID: {e}")
        return None

def has_admin_permission(user):
    """Проверяет, есть ли у пользователя одна из админских ролей"""
    try:
        for role_id in TAG_ROLE_IDS:
            role = discord.utils.get(user.roles, id=role_id)
            if role:
                return True
        return False
    except Exception as e:
        print(f"Ошибка проверки прав: {e}")
        return False

async def create_application_channel(guild, discord_user, discord_id, application):
    """Создает канал для заявки в указанной категории"""
    try:
        clean_name = re.sub(r'[^\w\s-]', '', discord_user)
        clean_name = re.sub(r'[-\s]+', '-', clean_name).strip().lower()
        
        channel_name = f"заявление-{clean_name}"
        
        category = guild.get_channel(APPLICATIONS_CATEGORY_ID)
        if not category:
            category = await guild.create_category("Заявки")
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        for role_id in TAG_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, 
                    send_messages=True, 
                    manage_messages=True, 
                    manage_channels=True
                )
        
        try:
            member = await guild.fetch_member(int(discord_id))
            overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        except:
            pass
        
        channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"Заявка от {application.username_static} | Discord: {discord_user} | ID: {discord_id}"
        )
        
        return channel
    except Exception as e:
        print(f"Ошибка создания канала: {e}")
        raise

async def delete_application_channel(channel, delay_seconds=5):
    """Удаляет канал заявки с задержкой"""
    await asyncio.sleep(delay_seconds)
    try:
        await channel.delete(reason="Заявка обработана")
    except Exception as e:
        print(f"Ошибка при удалении канала: {e}")

async def send_application_embed(channel, application, interaction_user, guild):
    """Отправляет заявку в новом формате"""
    try:
        role_mentions = []
        for role_id in TAG_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                role_mentions.append(f"<@&{role.id}>")
        
        if role_mentions:
            mentions_text = " ".join(role_mentions)
            await channel.send(f"{mentions_text} Новая заявка!")
        else:
            await channel.send("Новая заявка!")
        
        embed = discord.Embed(
            title="Заявление",
            color=discord.Color.blue(),
            timestamp=application.created_at
        )
        
        rollbacks_text = application.rollbacks
        if rollbacks_text and rollbacks_text.startswith("```") and rollbacks_text.endswith("```"):
            rollbacks_text = rollbacks_text[3:-3].strip()
        
        embed.add_field(name="Никнейм Статик", value=f"```{application.username_static}```", inline=False)
        embed.add_field(name="OOC имя возраст", value=f"```{application.ooc_info}```", inline=False)
        embed.add_field(name="История семей", value=f"```{application.fam_history}```", inline=False)
        embed.add_field(name="Почему выбрали именно нас?", value=f"```{application.reason}```", inline=False)
        embed.add_field(name="Откаты с ГГ", value=f"{rollbacks_text}", inline=False)
        embed.add_field(name="Пользователь", value=f"<@{application.discord_id}>", inline=False)
        embed.add_field(name="Username", value=f"```{application.discord_user}```", inline=True)
        embed.add_field(name="ID", value=f"```{application.discord_id}```", inline=True)
        
        user_previous_apps = await get_user_applications(application.discord_id)
        user_previous_apps = [app for app in user_previous_apps if app.status != "pending" and app.id != application.id]
        
        if user_previous_apps:
            logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
            log_links = []
            if logs_channel:
                async for message in logs_channel.history(limit=200):
                    if message.embeds:
                        for embed_msg in message.embeds:
                            user_found = False
                            for field in embed_msg.fields:
                                if field.value and application.discord_id in field.value:
                                    user_found = True
                                    break
                            
                            if not user_found and embed_msg.description and application.discord_id in embed_msg.description:
                                user_found = True
                            
                            if user_found:
                                status_icon = "✅" if embed_msg.title and "✅" in embed_msg.title else "❌"
                                log_links.append(f"{status_icon} [Ссылка]({message.jump_url})")
                                break
            
            if log_links:
                links_text = "\n".join(log_links[:5])
                embed.add_field(
                    name="Предыдущие заявки",
                    value=links_text,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Предыдущие заявки",
                    value="Заявок не найдено.",
                    inline=False
                )
        else:
            embed.add_field(
                name="Предыдущие заявки",
                value="Заявок не найдено.",
                inline=False
            )
        
        message = await channel.send(embed=embed)
        
        view = discord.ui.View(timeout=None)
        
        async def approve_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            application.status = "approved"
            application.moderator = interaction_btn.user.name
            application.updated_at = datetime.now()
            await save_application(application)
            
            try:
                user = await bot.fetch_user(int(application.discord_id))
                await user.send("🎉 **Вы приняты в семью!** 🎉\n\nДобро пожаловать! Ожидайте дальнейших инструкций от администрации.")
            except Exception as e:
                print(f"Не удалось отправить сообщение пользователю: {e}")
            
            await send_log_to_channel(application, interaction_btn.user, "approved", guild)
            
            try:
                await interaction_btn.message.edit(view=None)
            except:
                pass
            
            await channel.send(f"**Заявка принята рекрутом <@{interaction_btn.user.id}>**")
            bot.loop.create_task(delete_application_channel(channel))
            
            await interaction_btn.response.send_message("✅ Заявка принята! Канал будет удален через 5 секунд.", ephemeral=True)
        
        async def reject_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            modal = discord.ui.Modal(title="Причина отказа")
            reason_input = discord.ui.TextInput(
                label="Укажите причину отказа",
                style=discord.TextStyle.paragraph,
                placeholder="Например: стрельба мувмент",
                required=True,
                max_length=500
            )
            modal.add_item(reason_input)
            
            async def modal_callback(modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)
                
                application.status = "rejected"
                application.moderator = modal_interaction.user.name
                application.reason_reject = reason_input.value
                application.updated_at = datetime.now()
                await save_application(application)
                
                try:
                    user = await bot.fetch_user(int(application.discord_id))
                    await user.send(f"❌ **Ваша заявка отклонена.**\n\n**Причина:** {reason_input.value}\n\nВы можете подать заявку снова после устранения указанных замечаний.")
                except Exception as e:
                    print(f"Не удалось отправить сообщение пользователю: {e}")
                
                await send_log_to_channel(application, modal_interaction.user, "rejected", reason_input.value, guild)
                
                try:
                    await modal_interaction.message.edit(view=None)
                except:
                    pass
                
                await channel.send(f"**Заявка отклонена рекрутом <@{modal_interaction.user.id}>**\n**Причина:** {reason_input.value}")
                bot.loop.create_task(delete_application_channel(channel))
                
                await modal_interaction.followup.send("✅ Заявка отклонена! Канал будет удален через 5 секунд.", ephemeral=True)
            
            modal.on_submit = modal_callback
            await interaction_btn.response.send_modal(modal)
        
        async def consider_callback(interaction_btn: discord.Interaction):
            if not has_admin_permission(interaction_btn.user):
                await interaction_btn.response.send_message("❌ У вас нет прав для этого действия", ephemeral=True)
                return
            
            await interaction_btn.response.defer()
            await channel.send(f"**Заявка взята на рассмотрение рекрутом <@{interaction_btn.user.id}>**")
        
        approve_button = discord.ui.Button(style=discord.ButtonStyle.green, label="Принять", row=0)
        approve_button.callback = approve_callback
        
        consider_button = discord.ui.Button(style=discord.ButtonStyle.blurple, label="Взять на рассмотрение", row=0)
        consider_button.callback = consider_callback
        
        reject_button = discord.ui.Button(style=discord.ButtonStyle.red, label="Отклонить", row=0)
        reject_button.callback = reject_callback
        
        view.add_item(approve_button)
        view.add_item(consider_button)
        view.add_item(reject_button)
        
        await channel.send(view=view)
        
        application.message_id = message.id
        await save_application(application)
        
        return message, None
    except Exception as e:
        print(f"Ошибка отправки embed: {e}")
        raise

async def send_log_to_channel(application, moderator, action, reason=None, guild=None):
    """Отправляет лог о заявке в канал логов"""
    try:
        logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
        
        if not logs_channel:
            return
        
        embed = discord.Embed(
            title="✅ Заявка принята" if action == "approved" else "❌ Заявка отклонена",
            color=discord.Color.green() if action == "approved" else discord.Color.red(),
            timestamp=application.updated_at
        )
        
        embed.add_field(name="Никнейм Статик", value=application.username_static, inline=False)
        embed.add_field(name="OOC имя возраст", value=application.ooc_info, inline=False)
        embed.add_field(name="История семей", value=application.fam_history[:500] + "..." if len(application.fam_history) > 500 else application.fam_history, inline=False)
        
        if application.reason:
            embed.add_field(name="Причина выбора", value=application.reason[:500] + "..." if len(application.reason) > 500 else application.reason, inline=False)
        
        if application.rollbacks and application.rollbacks != "Не указано":
            rollbacks_text = application.rollbacks
            if rollbacks_text.startswith("```") and rollbacks_text.endswith("```"):
                rollbacks_text = rollbacks_text[3:-3].strip()
            embed.add_field(name="Откаты с ГГ", value=rollbacks_text[:500] + "..." if len(rollbacks_text) > 500 else rollbacks_text, inline=False)
        
        embed.add_field(name="Пользователь", value=f"<@{application.discord_id}>", inline=False)
        embed.add_field(name="Username", value=application.discord_user, inline=True)
        embed.add_field(name="ID", value=application.discord_id, inline=True)
        
        if action == "approved":
            embed.add_field(name="Принял", value=f"<@{moderator.id}>", inline=False)
        elif action == "rejected":
            embed.add_field(name="Отклонил", value=f"<@{moderator.id}>", inline=False)
            embed.add_field(name="Причина отказа", value=reason[:500] + "..." if len(reason) > 500 else reason, inline=False)
        
        await logs_channel.send(embed=embed)
    except Exception as e:
        print(f"Ошибка отправки лога: {e}")

class ApplicationForm(discord.ui.Modal, title='Подача заявки в семью'):
    """Модальная форма для подачи заявки"""
    
    nickname_static = discord.ui.TextInput(
        label='Никнейм и Статик Средний онлайн за день',
        placeholder='Например: Skeet Nyam 2253 6+ часов',
        max_length=100,
        required=True
    )
    
    ooc_info = discord.ui.TextInput(
        label='OOC имя и возраст',
        placeholder='Например: Серега 20',
        max_length=100,
        required=True
    )
    
    fam_history = discord.ui.TextInput(
        label='История семей',
        placeholder='Например: Waker ушел в инактив кикнули',
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )
    
    reason = discord.ui.TextInput(
        label='Почему выбрали именно нас?',
        placeholder='Например: с маркета + много вас видел на контенте',
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True
    )
    
    rollbacks = discord.ui.TextInput(
        label='Откаты с ГГ (ссылки)',
        placeholder='Например: https://youtu.be/ спешик',
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_active_apps = await get_user_applications(str(interaction.user.id))
            user_active_apps = [app for app in user_active_apps if app.status == "pending"]
            
            if user_active_apps:
                await interaction.response.send_message(
                    "❌ У вас уже есть активная заявка на рассмотрении!\n"
                    "Вы не можете подать новую заявку, пока предыдущая не будет обработана.",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            application = Application(
                username_static=self.nickname_static.value.strip(),
                ooc_info=self.ooc_info.value.strip(),
                fam_history=self.fam_history.value,
                reason=self.reason.value,
                rollbacks=self.rollbacks.value if self.rollbacks.value else "Не указано",
                discord_user=interaction.user.name,
                discord_id=str(interaction.user.id)
            )
            
            channel = await create_application_channel(interaction.guild, interaction.user.name, interaction.user.id, application)
            application.channel_id = channel.id
            
            message, _ = await send_application_embed(channel, application, interaction.user, interaction.guild)
            
            await interaction.followup.send(
                f"✅ Ваша заявка успешно отправлена!\n\n"
                f"Заявка рассматривается в течение суток.\n"
                f"Ответ придёт в личные сообщения от бота.\n"
                f"Для обсуждения заявки создан канал: <#{application.channel_id}>",
                ephemeral=True
            )
            
        except Exception as e:
            print(f"Ошибка при создании заявки: {e}")
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "❌ Ошибка при создании заявки. Пожалуйста, попробуйте позже.", 
                    ephemeral=True
                )
            except:
                pass
    
    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Ошибка в форме заявки: {error}")
        traceback.print_exc()
        try:
            await interaction.followup.send(
                '❌ Произошла ошибка при отправке заявки. Пожалуйста, попробуйте позже.', 
                ephemeral=True
            )
        except:
            pass

@bot.event
async def on_ready():
    print(f'✅ {bot.user} запущен!')
    print(f'ID бота: {bot.user.id}')
    
    await init_database()
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} slash-команд")
    except Exception as e:
        print(f"❌ Ошибка синхронизации slash-команд: {e}")
    
    for guild in bot.guilds:
        print(f'Сервер: {guild.name} (ID: {guild.id})')
        if guild.id == 1003525677640851496:
            print(f'  → Основной сервер: {guild.name}')
            print(f'  → Админские роли: {len(TAG_ROLE_IDS)}')
            print(f'  → Роли для slash-команд: {len(SLASH_COMMAND_ROLE_IDS)}')
    
    print('Бот готов к работе!')

@bot.event
async def on_error(event, *args, **kwargs):
    print(f'Ошибка в событии {event}:')
    traceback.print_exc()

# ============ SLASH COMMANDS ============

@bot.tree.command(
    name="заявко",
    description="Создает панель для подачи заявки в семью"
)
async def slash_create_application_panel(interaction: discord.Interaction):
    """Slash-команда для создания панели заявки"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="**ЗАЯВКА В СЕМЬЮ**",
            color=discord.Color.from_rgb(0, 0, 0)
        )
        
        embed.add_field(
            name="**<a:wave:1449952532129517570> Путь в семью начинается здесь!**\n\u200b",
            value=(
                "**<:outputonlinepngtools:1449964820999700721> После заполнения анкеты Вам придет оповещение в ЛС от бота с результатом (ответ не придёт, если закрыт доступ к сообщениям в discord) **\n\n"
                "-# Заявка рассматривается в течении суток. САЙГИ ОБЯЗАТЕЛЬНЫ."
            ),
            inline=False
        )
        
        embed.set_image(url=IMAGE_URL)
        embed.set_footer(text="Amnyamov famq", icon_url=SMALL_ICON_URL)
        
        class ApplicationButtonView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)
            
            @discord.ui.button(
                label="Подать заявку",
                emoji="<:icons848:1449967782308614244>",
                style=discord.ButtonStyle.gray,
                custom_id="apply_button_amnyamov",
                row=0
            )
            async def apply_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_modal(ApplicationForm())
        
        await interaction.response.send_message(embed=embed, view=ApplicationButtonView())
        
    except Exception as e:
        print(f"Ошибка команды заявка: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Произошла ошибка при создании панели.", ephemeral=True)

@bot.tree.command(
    name="заявки",
    description="Показать все заявки"
)
async def slash_applications_list(interaction: discord.Interaction):
    """Slash-команда для просмотра заявок"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        pending_apps = await get_pending_applications()
        all_apps = await load_applications()
        
        approved_apps = [app for app in all_apps if app.status == "approved"]
        rejected_apps = [app for app in all_apps if app.status == "rejected"]
        
        embed = discord.Embed(
            title="📋 Активные заявки",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.add_field(name="⏳ На рассмотрении", value=str(len(pending_apps)), inline=True)
        embed.add_field(name="✅ Принято", value=str(len(approved_apps)), inline=True)
        embed.add_field(name="❌ Отклонено", value=str(len(rejected_apps)), inline=True)
        
        if pending_apps:
            apps_text = ""
            for app in pending_apps[:5]:
                channel_info = f"<#{app.channel_id}>" if app.channel_id else "Канал не создан"
                apps_text += f"• **{app.username_static}** - {channel_info}\n"
            embed.add_field(name="Последние заявки:", value=apps_text, inline=False)
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"Ошибка команды заявки: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Произошла ошибка при получении списка заявок.", ephemeral=True)

@bot.tree.command(
    name="очистка",
    description="Очистка старых каналов с заявками"
)
async def slash_cleanup_channels(interaction: discord.Interaction):
    """Slash-команда для очистки каналов"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        category = interaction.guild.get_channel(APPLICATIONS_CATEGORY_ID)
        
        if not category:
            await interaction.followup.send("Категория заявок не найдена.")
            return
        
        deleted = 0
        for channel in category.channels:
            if hasattr(channel, 'created_at'):
                age = datetime.now() - channel.created_at.replace(tzinfo=None)
                if age.days > 30:
                    try:
                        await channel.delete(reason="Очистка старых заявок")
                        deleted += 1
                    except:
                        pass
        
        await interaction.followup.send(f"✅ Удалено {deleted} старых каналов с заявками.")
    except Exception as e:
        print(f"Ошибка команды очистка: {e}")
        traceback.print_exc()
        await interaction.followup.send("❌ Произошла ошибка при очистке каналов.")

@bot.tree.command(
    name="статус",
    description="Проверить статус заявки пользователя"
)
@app_commands.describe(
    пользователь="Пользователь для проверки (оставьте пустым для себя)"
)
async def slash_application_status(interaction: discord.Interaction, пользователь: discord.User = None):
    """Slash-команда для проверки статуса заявки"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        if пользователь is None:
            discord_id = str(interaction.user.id)
            user_mention = f"<@{discord_id}>"
        else:
            discord_id = str(пользователь.id)
            user_mention = f"<@{discord_id}>"
        
        user_apps = await get_user_applications(discord_id)
        
        if not user_apps:
            await interaction.response.send_message("Заявок не найдено.")
            return
        
        embed = discord.Embed(
            title=f"Заявки пользователя {user_mention}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        for i, app in enumerate(user_apps[:3], 1):
            status_emoji = "⏳" if app.status == "pending" else "✅" if app.status == "approved" else "❌"
            status_text = "На рассмотрении" if app.status == "pending" else "Принята" if app.status == "approved" else "Отклонена"
            
            app_info = f"**Статус:** {status_emoji} {status_text}\n"
            app_info += f"**Никнейм и статик:** {app.username_static}\n"
            
            if app.channel_id:
                app_info += f"**Канал:** <#{app.channel_id}>\n"
            
            if app.status == "rejected" and app.reason_reject:
                app_info += f"**Причина отказа:** {app.reason_reject[:100]}...\n"
            
            if app.status == "approved" and app.moderator:
                app_info += f"**Принял:** <@{next((m.id for m in interaction.guild.members if m.name == app.moderator), app.moderator)}>\n"
            
            app_info += f"**Дата:** {app.created_at.strftime('%d.%m.%Y %H:%M')}"
            
            embed.add_field(name=f"Заявка #{i}", value=app_info, inline=False)
        
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        print(f"Ошибка команды статус: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Произошла ошибка при проверке статуса.", ephemeral=True)

@bot.tree.command(
    name="удалить_канал",
    description="Вручную удалить канал заявки"
)
@app_commands.describe(
    канал="Канал для удаления (оставьте пустым для текущего канала)"
)
async def slash_delete_channel_manual(interaction: discord.Interaction, канал: discord.TextChannel = None):
    """Slash-команда для удаления канала"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        if канал is None:
            category = interaction.guild.get_channel(APPLICATIONS_CATEGORY_ID)
            
            if category and interaction.channel.category_id == category.id:
                channel = interaction.channel
            else:
                await interaction.response.send_message(
                    "❌ Укажите канал или выполните команду в канале заявки.",
                    ephemeral=True
                )
                return
        else:
            channel = канал
        
        await channel.delete(reason="Ручное удаление администратором")
        await interaction.response.send_message(f"✅ Канал {channel.name} удален.", ephemeral=True)
    except Exception as e:
        print(f"Ошибка команды удалить_канал: {e}")
        traceback.print_exc()
        await interaction.response.send_message(f"❌ Ошибка при удалении канала: {str(e)}", ephemeral=True)

@bot.tree.command(
    name="тест",
    description="Тестовая команда для проверки работы бота"
)
async def slash_test_command(interaction: discord.Interaction):
    """Slash-команда для теста"""
    try:
        if not has_slash_command_permission(interaction):
            await interaction.response.send_message(
                "❌ У вас нет прав для выполнения этой команды.\n"
                "Требуется одна из ролей: <@&1310673963000528949> или <@&1381685630555258931>",
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(f"✅ Бот работает! Пинг: {round(bot.latency * 1000)}мс")
    except Exception as e:
        print(f"Ошибка команды тест: {e}")
        traceback.print_exc()
        await interaction.response.send_message("❌ Произошла ошибка при выполнении команды.", ephemeral=True)

# ============ КОМАНДЫ С ПРЕФИКСОМ ! ============

@bot.command(name="заявко")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_create_application_panel(ctx):
    """Старая команда для создания панели заявки"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/заявко`")

@bot.command(name="заявки")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_applications_list(ctx):
    """Старая команда для просмотра заявок"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/заявки`")

@bot.command(name="очистка")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_cleanup_channels(ctx):
    """Старая команда для очистки каналов"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/очистка`")

@bot.command(name="статус")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_application_status(ctx, discord_id: str = None):
    """Старая команда для проверки статуса"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/статус`")

@bot.command(name="удалить_канал")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_delete_channel_manual(ctx, channel_id: str = None):
    """Старая команда для удаления канала"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/удалить_канал`")

@bot.command(name="тест")
@commands.has_any_role(*SLASH_COMMAND_ROLE_IDS)
async def legacy_test_command(ctx):
    """Старая тестовая команда"""
    await ctx.send("⚠️ Эта команда устарела. Пожалуйста, используйте slash-команду `/тест`")

# Обработка ошибок команд
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingAnyRole):
        await ctx.send("❌ У вас недостаточно прав для выполнения этой команды.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас недостаточно прав для выполнения этой команды.")
    else:
        print(f"Ошибка команды {ctx.command}: {error}")
        traceback.print_exc()
        await ctx.send("❌ Произошла ошибка при выполнении команды.")

@bot.event
async def on_disconnect():
    print("Бот отключился. Пытаюсь переподключиться...")

# Запуск бота
if __name__ == "__main__":
    print("=" * 50)
    print("Запуск Discord бота для системы заявок")
    print(f"Токен получен: {'Да' if TOKEN else 'Нет'}")
    print(f"Database URL получен: {'Да' if DATABASE_URL else 'Нет'}")
    print("=" * 50)
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"Критическая ошибка при запуске бота: {e}")
        traceback.print_exc()
        sys.exit(1)