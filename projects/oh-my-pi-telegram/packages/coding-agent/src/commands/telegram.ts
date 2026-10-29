/**
 * `omp telegram` — run the Telegram bridge in the foreground — and
 * `omp telegram status`, a config-sanity report that never prints the token.
 *
 * The run form is built like `omp acp`: parse the launch flags, force
 * `mode: "telegram"`, and hand the args to the shared root bootstrap so the
 * bridge gets the same settings, auth, model registry, and session options as
 * any other mode.
 */
import { randomBytes } from "node:crypto";
import { Command } from "@oh-my-pi/pi-utils/cli";
import { type Args as ParsedArgs, parseArgs, reportCliUsageError } from "../cli/args";
import { telegramHelp as commandHelp } from "../cli/command-help";
import { Settings } from "../config/settings";
import { TelegramBotApi } from "../telegram/api";
import { telegramStatusReport } from "../telegram/headless";
import { acquireTelegramHostLock } from "../telegram/lock";
import { startTelegramPairing } from "../telegram/pairing";
import {
	cfgTelegramAllowedUserIds,
	cfgTelegramChatId,
	readTelegramTokenConfig,
} from "../telegram/settings";
export default class Telegram extends Command {
	static description = commandHelp.description;
	static strict = false;

	static examples = ["omp telegram", "omp telegram status", "omp telegram --model anthropic/claude-sonnet-4-5"];

	async run(): Promise<void> {
		const raw = this.argv;
		if (raw[0] === "status") {
			if (raw.length > 1) {
				process.stderr.write("error: telegram status takes no arguments (usage: omp telegram status)\n");
				process.exitCode = 2;
				return;
			}
			const settings = await Settings.loadReadOnly({ cwd: process.cwd() });
			const report = await telegramStatusReport({ settings, cwd: process.cwd() });
			for (const line of report.lines) process.stdout.write(`${line}\n`);
			process.exitCode = report.code;
			return;
		}
		if (raw[0] === "pair") {
			const settings = await Settings.init({ cwd: process.cwd() });
			const base = readTelegramTokenConfig(settings, process.cwd());
			if (!base.ok) {
				process.stderr.write(`error: ${base.message}\n`);
				process.exitCode = 1;
				return;
			}

			let lock;
			try {
				lock = await acquireTelegramHostLock(base.config.botId);
			} catch (error) {
				process.stderr.write(`error: Telegram state directory could not be created: ${String(error)}\n`);
				process.exitCode = 2;
				return;
			}
			if (!lock.ok) {
				const who = lock.holderPid === null ? "" : ` (pid ${lock.holderPid})`;
				process.stderr.write(`error: Telegram host for this bot is already running${who}. Stop it before pairing.\n`);
				process.exitCode = 1;
				return;
			}

			const code = randomBytes(4).toString("hex");
			const api = new TelegramBotApi({ token: base.config.token });

			let botUsername: string | null = null;
			try {
				const me = await api.getMe();
				botUsername = me.username ?? null;
			} catch {
				// handled by startTelegramPairing
			}

			const link = botUsername ? `https://t.me/${botUsername}?start=${code}` : null;

			process.stdout.write(`\n=== Telegram Pairing ===\n`);
			process.stdout.write(`Pairing code: ${code}\n`);
			if (link) {
				process.stdout.write(`Deep link:    ${link}\n`);
			}
			process.stdout.write(`Send /pair ${code} or /start ${code} to your bot in Telegram.\n`);
			process.stdout.write(`Waiting up to 10 minutes (Ctrl+C to cancel)...\n\n`);

			const run = startTelegramPairing({ api, code });

			process.on("SIGINT", () => {
				run.cancel();
				void lock.lease.release().catch(() => {});
				process.exit(130);
			});

			const outcome = await run.outcome;
			await lock.lease.release().catch(() => {});

			if (outcome.kind === "paired") {
				cfgTelegramChatId.set(settings, String(outcome.chatId));
				const ids = new Set<number>();
				for (const entry of cfgTelegramAllowedUserIds.get(settings)) {
					const numeric = typeof entry === "number" ? entry : Number(String(entry).trim());
					if (Number.isInteger(numeric) && numeric !== 0) ids.add(numeric);
				}
				ids.add(outcome.userId);
				cfgTelegramAllowedUserIds.set(settings, [...ids]);
				await settings.flush();

				process.stdout.write(`✓ Successfully paired with ${outcome.chatTitle} (chat: ${outcome.chatId}, user: ${outcome.userId})!\n`);
				process.stdout.write(`Configuration saved to ~/.omp/agent/config.yml.\n`);
				try {
					await api.sendMessage({
						chatId: outcome.chatId,
						text: "🎉 Paired with OMP! This chat now drives omp sessions. Send /help to see available commands.",
					});
				} catch {
					// ignore
				}
				process.exitCode = 0;
				return;
			}

			if (outcome.kind === "refused") {
				process.stderr.write(`Refusal: ${outcome.message}\n`);
				process.exitCode = 1;
				return;
			}
			if (outcome.kind === "timeout") {
				process.stderr.write(`Pairing timed out. Run 'omp telegram pair' to try again.\n`);
				process.exitCode = 1;
				return;
			}
			if (outcome.kind === "cancelled") {
				process.stderr.write(`Pairing cancelled.\n`);
				process.exitCode = 1;
				return;
			}
		}
		// `omp telegram start` is the explicit spelling of the default run form.
		const args = raw[0] === "start" ? raw.slice(1) : raw;
		let parsed: ParsedArgs;
		try {
			parsed = parseArgs(args);
		} catch (error) {
			if (reportCliUsageError(error)) {
				process.exitCode = 2;
				return;
			}
			throw error;
		}
		parsed.mode = "telegram";
		// Branch-only runner: `omp telegram status` and `--help` must stay light and
		// must not import the full agent bootstrap.
		const { runRootCommand } = await import("../main");
		await runRootCommand(parsed, args);
	}
}
