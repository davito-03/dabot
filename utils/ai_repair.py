import os
import json
import logging
import datetime
import traceback

class RepairEngine:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Dabot_Repair')

    async def propose_fixes(self, issues):
        """
        Analyzes the list of issues and returns a list of proposed fixes.
        Each fix is a dict: {'type': 'translation|config|code', 'description': '...', 'action_data': ...}
        """
        fixes = []
        
        # 1. Translation Missing Keys
        translation_issues = [i for i in issues if i['type'] == 'translation_missing']
        if translation_issues:
            # Group by language
            langs_affected = list(set([i['data']['lang'] for i in translation_issues]))
            
            for lang in langs_affected:
                missing_keys = [i['data'] for i in translation_issues if i['data']['lang'] == lang]
                if missing_keys:
                    fixes.append({
                        'id': f"fix_trans_{lang}",
                        'type': 'translation',
                        'description': f"Auto-translate {len(missing_keys)} missing keys for '{lang}' using AI.",
                        'data': {'lang': lang, 'keys': missing_keys}
                    })

        # 2. Add other automatic repairs here (e.g. creating missing folders)
        
        return fixes


    async def _fix_translations(self, data):
        """
        Generates translations for missing keys using the Chatbot AI and saves them.
        """
        lang = data['lang']
        keys_to_fix = data['keys'] # List of {key: 'keyname', 'base_value': 'English text'}
        
        chatbot = self.bot.get_cog('Chatbot')
        if not chatbot:
            return False, "Chatbot Cog not loaded, cannot use AI."

        # Prepare Prompt
        lines = []
        for item in keys_to_fix:
            lines.append(f"{item['key']}: {item['base_value']}")
        
        content_to_translate = "\n".join(lines)
        
        prompt = (
            f"Translate the following lines to '{lang}'. Return ONLY a valid JSON object "
            f"where keys match the input keys and values are the translations. "
            f"Do not include Markdown formatting or ```json blocks. Just raw JSON.\n\n{content_to_translate}"
        )
        
        try:
            # Use AI
            msgs = [{"role": "user", "content": prompt}]
            response_text, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False)
            
            # Clean response
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            # Parse JSON
            new_translations = json.loads(response_text)
            
            # Load existing file
            file_path = f"langs/{lang}.json"
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
            else:
                current_data = {}
            
            # Ensure slash_commands exists
            if 'slash_commands' not in current_data:
                current_data['slash_commands'] = {}
            
            count = 0
            # Merge into slash_commands directly as per the file structure
            for k, v in new_translations.items():
                # We overwrite or add
                current_data['slash_commands'][k] = v
                count += 1

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(current_data, f, indent=4, ensure_ascii=False)
            
            # Reload i18n
            await self.bot.i18n.load_translations()
            return True, f"✅ Translated & Saved {count} keys for {lang}."

        except Exception as e:
            return False, f"Translation fix failed: {e}"

    async def analyze_log_content(self, log_path):
        """
        Reads the log file (with a size limit) and asks the AI to analyze it for root causes.
        """
        if not os.path.exists(log_path):
            return "❌ Log file not found."
            
        try:
            # Read file, limit to last 200KB to be safe with tokens but generous
            file_size = os.path.getsize(log_path)
            read_mode = "r"
            
            content = ""
            with open(log_path, "r", encoding="utf-8", errors='replace') as f:
                if file_size > 200000:
                    f.seek(file_size - 200000)
                    content = f.read()
                    content = "[...Older logs truncated...]\n" + content
                else:
                    content = f.read()
            
            if not content.strip():
                return "⚠️ Log file is empty."
                
            chatbot = self.bot.get_cog('Chatbot')
            if not chatbot:
                return "⚠️ Chatbot Cog not loaded, cannot perform AI analysis."
                
            prompt = (
                "Analyze the following Discord Bot log file. "
                "Identify any Critical Errors, Warnings, or odd behaviors. "
                "Specifically check for:\n"
                "- '429 Quota Exceeded' (Google/Gemini API limits)\n"
                "- '404 Not Found' (Invalid AI Model names)\n"
                "- Blocking loop detections or timeouts.\n"
                "Ignore standard info logs unless they indicate a restart loop or issue. "
                "Summarize the health status and point out the root cause of any crashes.\n\n"
                f"```log\n{content}\n```"
            )
            
            # Use AI
            msgs = [{"role": "user", "content": prompt}]
            response_text, _, _ = await chatbot.ai.generate_response(msgs, use_tools=False)
            
            return response_text
            
        except Exception as e:
            return f"❌ Failed to analyze log: {e}"

    # --- SAFETY SYSTEM ---

    def create_backup(self, file_paths):
        """
        Creates a timestamped backup of the specified files.
        Returns the backup_id (folder name).
        """
        import shutil
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_id = f"repair_{timestamp}"
        backup_dir = os.path.join("backups", backup_id)
        
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        manifest = {}
        
        for path in file_paths:
            if os.path.exists(path):
                filename = os.path.basename(path)
                dest = os.path.join(backup_dir, filename)
                shutil.copy2(path, dest)
                manifest[path] = dest # Original -> Backup
                
        # Save manifest
        with open(os.path.join(backup_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
            
        return backup_id

    def restore_backup(self, backup_id):
        """Restores files from a backup ID."""
        import shutil
        backup_dir = os.path.join("backups", backup_id)
        manifest_path = os.path.join(backup_dir, "manifest.json")
        
        if not os.path.exists(manifest_path):
            return False, "Backup not found."
            
        try:
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
                
            for original_path, backup_path in manifest.items():
                shutil.copy2(backup_path, original_path)
                
            return True, f"Restored {len(manifest)} files from {backup_id}."
        except Exception as e:
            return False, f"Restore failed: {e}"

    async def apply_fix(self, fix):
        """Executes a specific fix."""
        # Fix types
        if fix['type'] == 'translation':
            # Identify target file for both backup and fix
            lang = fix['data']['lang']
            target_file = f"langs/{lang}.json"
            
            # Create Backup
            backup_id = self.create_backup([target_file])
            
            # Apply Fix
            success, msg = await self._fix_translations(fix['data'])
            
            if success:
                return True, f"{msg} (Backup: {backup_id})", backup_id
            return False, msg, None

        return False, "Unknown fix type", None

    # --- RESTART & ROLLBACK SAFETY ---

    def save_repair_state(self, channel_id, backup_ids):
        """Saves the state before a restart to track if it crashes."""
        state = {
            "status": "pending_restart",
            "timestamp": datetime.datetime.now().isoformat(),
            "channel_id": channel_id,
            "backup_ids": backup_ids
        }
        with open("repair_state.json", "w") as f:
            json.dump(state, f)

    def check_repair_state(self):
        """Checks if we are recovering from a repair restart."""
        if not os.path.exists("repair_state.json"):
            return None
        
        try:
            with open("repair_state.json", "r") as f:
                state = json.load(f)
            return state
        except:
            return None

    def clear_repair_state(self):
        """Clears the repair state (success)."""
        if os.path.exists("repair_state.json"):
            os.remove("repair_state.json")

    def mark_repair_faulty(self):
        """Marks the current state as faulty/reverted (used by main.py on crash)."""
        state = self.check_repair_state()
        if state:
            state['status'] = 'reverted' # or 'crashed'
            with open("repair_state.json", "w") as f:
                json.dump(state, f)
            return state
        return None
