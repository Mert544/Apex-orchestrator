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
        })
    );
}
