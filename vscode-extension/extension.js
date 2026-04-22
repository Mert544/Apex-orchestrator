const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');

function getPythonPath() {
    return vscode.workspace.getConfiguration('apex').get('pythonPath', 'python');
}

function getProjectRoot() {
    const configured = vscode.workspace.getConfiguration('apex').get('projectRoot', '');
    if (configured) return configured;
    const folders = vscode.workspace.workspaceFolders;
    return folders ? folders[0].uri.fsPath : process.cwd();
}

function runApex(plan, env = {}) {
    const python = getPythonPath();
    const root = getProjectRoot();
    const apexDir = path.join(__dirname, '..');

    const childEnv = { ...process.env, ...env, EPISTEMIC_TARGET_ROOT: root, EPISTEMIC_AUTOMATION_PLAN: plan };

    const child = spawn(python, ['-m', 'app.main'], {
        cwd: apexDir,
        env: childEnv,
        shell: false,
    });

    const outputChannel = vscode.window.createOutputChannel('Apex Orchestrator');
    outputChannel.show();
    outputChannel.appendLine(`Running Apex plan: ${plan}`);
    outputChannel.appendLine(`Project root: ${root}`);
    outputChannel.appendLine('---');

    child.stdout.on('data', (data) => {
        outputChannel.append(data.toString());
    });

    child.stderr.on('data', (data) => {
        outputChannel.append(data.toString());
    });

    child.on('close', (code) => {
        outputChannel.appendLine(`---`);
        outputChannel.appendLine(`Apex finished with code ${code}`);
        if (code === 0) {
            vscode.window.showInformationMessage(`Apex ${plan} completed successfully.`);
        } else {
            vscode.window.showErrorMessage(`Apex ${plan} failed with code ${code}. Check Output > Apex Orchestrator.`);
        }
    });
}

function activate(context) {
    const disposables = [
        vscode.commands.registerCommand('apex.projectScan', () => {
            runApex('project_scan');
        }),
        vscode.commands.registerCommand('apex.semanticPatch', async () => {
            const editor = vscode.window.activeTextEditor;
            const file = editor ? vscode.workspace.asRelativePath(editor.document.uri) : '';
            const title = await vscode.window.showInputBox({ prompt: 'Patch title', value: 'Add docstrings' });
            if (!title) return;
            runApex('semantic_patch_loop', { EPISTEMIC_FOCUS_FILE: file });
        }),
        vscode.commands.registerCommand('apex.runTests', () => {
            runApex('verify_project');
        }),
        vscode.commands.registerCommand('apex.openPresence', () => {
            const root = getProjectRoot();
            const presenceUri = vscode.Uri.file(path.join(root, '.apex', 'presence.md'));
            vscode.workspace.openTextDocument(presenceUri).then(
                (doc) => vscode.window.showTextDocument(doc),
                () => vscode.window.showWarningMessage('No presence.md found. Run an Apex plan first.')
            );
        }),
    ];

    context.subscriptions.push(...disposables);
}

function deactivate() {}

module.exports = { activate, deactivate };
