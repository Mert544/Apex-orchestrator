import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

function getConfig(): { pythonPath: string; projectRoot: string } {
    const config = vscode.workspace.getConfiguration('apex');
    let projectRoot = config.get<string>('projectRoot', '');
    if (!projectRoot && vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
        projectRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
    }
    return {
        pythonPath: config.get<string>('pythonPath', 'python'),
        projectRoot,
    };
}

function runApex(args: string[], cwd: string, pythonPath: string): Promise<string> {
    return new Promise((resolve, reject) => {
        const cmd = `${pythonPath} -m app.cli ${args.join(' ')}`;
        cp.exec(cmd, { cwd, timeout: 120000 }, (err, stdout, stderr) => {
            if (err && !stdout) {
                reject(stderr || err.message);
                return;
            }
            resolve(stdout || stderr);
        });
    });
}

export function activate(context: vscode.ExtensionContext) {
    const scanCommand = vscode.commands.registerCommand('apex.projectScan', async () => {
        const { pythonPath, projectRoot } = getConfig();
        if (!projectRoot) {
            vscode.window.showErrorMessage('Apex: No project root configured or workspace open.');
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Apex: Running project scan...',
            cancellable: false,
        }, async () => {
            try {
                const output = await runApex(['scan', '--plan=project_scan', `--target=${projectRoot}`], projectRoot, pythonPath);
                const panel = vscode.window.createWebviewPanel('apexScan', 'Apex Project Scan', vscode.ViewColumn.One, {});
                panel.webview.html = `<pre>${output.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>`;
            } catch (err) {
                vscode.window.showErrorMessage(`Apex scan failed: ${err}`);
            }
        });
    });

    const patchCommand = vscode.commands.registerCommand('apex.semanticPatch', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('Apex: No active file.');
            return;
        }
        const filePath = editor.document.uri.fsPath;
        const { pythonPath, projectRoot } = getConfig();
        if (!projectRoot) {
            vscode.window.showErrorMessage('Apex: No project root configured.');
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Apex: Generating semantic patch...',
            cancellable: false,
        }, async () => {
            try {
                const output = await runApex(['fractal', 'analyze', `--target=${projectRoot}`, '--depth=3'], projectRoot, pythonPath);
                vscode.window.showInformationMessage('Apex: Patch analysis complete. Check output panel.');
                const channel = vscode.window.createOutputChannel('Apex Semantic Patch');
                channel.appendLine(output);
                channel.show();
            } catch (err) {
                vscode.window.showErrorMessage(`Apex patch failed: ${err}`);
            }
        });
    });

    const testCommand = vscode.commands.registerCommand('apex.runTests', async () => {
        const { pythonPath, projectRoot } = getConfig();
        if (!projectRoot) {
            vscode.window.showErrorMessage('Apex: No project root configured.');
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Apex: Running tests...',
            cancellable: false,
        }, async () => {
            try {
                const output = await runApex(['run', '--plan=verify_project', `--target=${projectRoot}`], projectRoot, pythonPath);
                const channel = vscode.window.createOutputChannel('Apex Tests');
                channel.appendLine(output);
                channel.show();
            } catch (err) {
                vscode.window.showErrorMessage(`Apex tests failed: ${err}`);
            }
        });
    });

    const presenceCommand = vscode.commands.registerCommand('apex.openPresenceLog', async () => {
        const { projectRoot } = getConfig();
        if (!projectRoot) {
            vscode.window.showErrorMessage('Apex: No project root configured.');
            return;
        }
        const presencePath = path.join(projectRoot, '.apex', 'presence.md');
        if (!fs.existsSync(presencePath)) {
            vscode.window.showWarningMessage('Apex: No presence log found.');
            return;
        }
        const doc = await vscode.workspace.openTextDocument(presencePath);
        await vscode.window.showTextDocument(doc);
    });

    context.subscriptions.push(scanCommand, patchCommand, testCommand, presenceCommand);
}

export function deactivate() {}
