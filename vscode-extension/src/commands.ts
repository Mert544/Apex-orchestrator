import * as vscode from 'vscode';
import { runApex } from './runner';
import { ApexResultsProvider } from './treeProvider';
import { ApexDiagnostics } from './diagnostics';

export function registerCommands(
    context: vscode.ExtensionContext,
    outputChannel: vscode.OutputChannel,
    treeProvider: ApexResultsProvider,
    diagnostics: ApexDiagnostics,
    statusBar: vscode.StatusBarItem
) {
    const setStatus = (state: 'idle' | 'scanning' | 'success' | 'error') => {
        const icons: Record<string, string> = {
            idle: '$(search) Apex',
            scanning: '$(loading~spin) Scanning...',
            success: '$(check) Apex',
            error: '$(error) Apex'
        };
        statusBar.text = icons[state];
    };

    const runWithProgress = async (plan: string, env?: Record<string, string>) => {
        setStatus('scanning');
        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Apex: ${plan}`,
            cancellable: true
        }, async (progress, token) => {
            const result = await runApex(plan, outputChannel, env);
            if (result) {
                treeProvider.setResults(result.risks || []);
                diagnostics.update(result.risks || []);
                setStatus('success');
                vscode.commands.executeCommand('setContext', 'apex.hasResults', true);
            } else {
                setStatus('error');
            }
        });
    };

    context.subscriptions.push(
        vscode.commands.registerCommand('apex.projectScan', () => 
            runWithProgress('project_scan')),
        vscode.commands.registerCommand('apex.semanticPatch', () => 
            runWithProgress('semantic_patch_loop', { EPISTEMIC_FOCUS_FILE: vscode.window.activeTextEditor?.document.fileName || '' })),
        vscode.commands.registerCommand('apex.runTests', () => 
            runWithProgress('verify_project')),
        vscode.commands.registerCommand('apex.openPresence', () => {
            const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
            if (root) {
                vscode.workspace.openTextDocument(vscode.Uri.file(`${root}/.apex/presence.md`))
                    .then(doc => vscode.window.showTextDocument(doc));
            }
        }),
        vscode.commands.registerCommand('apex.refreshResults', () => treeProvider.refresh()),
        vscode.commands.registerCommand('apex.clearResults', () => {
            treeProvider.clear();
            diagnostics.clear();
            vscode.commands.executeCommand('setContext', 'apex.hasResults', false);
            setStatus('idle');
        }),
        vscode.commands.registerCommand('apex.autonomousRun', async () => {
            const config = vscode.workspace.getConfiguration('apex');
            const goal = await vscode.window.showInputBox({
                prompt: 'Enter a natural-language goal',
                placeHolder: 'e.g. security audit, fix docstrings',
                value: config.get<string>('defaultGoal', 'scan project')
            });
            if (!goal) { return; }
            const mode = await vscode.window.showQuickPick(
                ['report', 'supervised', 'autonomous'],
                { placeHolder: 'Select execution mode', canPickMany: false }
            ) as string | undefined;
            if (!mode) { return; }
            setStatus('scanning');
            outputChannel.appendLine(`[autonomous] Goal: ${goal} | Mode: ${mode}`);
            await runApex('run', outputChannel, {
                APEX_GOAL: goal,
                APEX_MODE: mode,
            });
            setStatus('success');
        }),
        vscode.commands.registerCommand('apex.daemonStart', async () => {
            const config = vscode.workspace.getConfiguration('apex');
            const goal = await vscode.window.showInputBox({
                prompt: 'Daemon goal',
                value: config.get<string>('defaultGoal', 'scan project')
            });
            if (!goal) { return; }
            const interval = config.get<number>('daemonInterval', 3600);
            outputChannel.appendLine(`[daemon] Starting with goal: ${goal}, interval: ${interval}s`);
            await runApex('daemon', outputChannel, {
                APEX_DAEMON_ACTION: 'start',
                APEX_GOAL: goal,
                APEX_DAEMON_INTERVAL: String(interval),
            });
            vscode.window.showInformationMessage('Apex daemon started');
        }),
        vscode.commands.registerCommand('apex.daemonStop', async () => {
            await runApex('daemon', outputChannel, { APEX_DAEMON_ACTION: 'stop' });
            vscode.window.showInformationMessage('Apex daemon stopped');
        }),
        vscode.commands.registerCommand('apex.daemonStatus', async () => {
            await runApex('daemon', outputChannel, { APEX_DAEMON_ACTION: 'status' });
        })
    );
}
