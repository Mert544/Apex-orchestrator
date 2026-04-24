import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

export function runApex(
    plan: string,
    outputChannel: vscode.OutputChannel,
    extraEnv?: Record<string, string>
): Promise<{ risks: any[] } | null> {
    return new Promise((resolve) => {
        const config = vscode.workspace.getConfiguration('apex');
        const pythonPath = config.get<string>('pythonPath', 'python');
        let projectRoot = config.get<string>('projectRoot', '');

        if (!projectRoot && vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
            projectRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
        }

        const extensionDir = path.dirname(__dirname);
        const apexRoot = path.resolve(extensionDir, '..');

        const env = {
            ...process.env,
            EPISTEMIC_TARGET_ROOT: projectRoot,
            EPISTEMIC_AUTOMATION_PLAN: plan,
            ...extraEnv
        };

        outputChannel.clear();
        outputChannel.show();
        outputChannel.appendLine(`[Apex] Running plan: ${plan}`);
        outputChannel.appendLine(`[Apex] Project root: ${projectRoot}`);

        // Build command based on plan type
        let args: string[];
        if (plan === 'run' && extraEnv?.APEX_GOAL) {
            args = ['-m', 'app.cli', 'run', '--goal', extraEnv.APEX_GOAL, '--mode', extraEnv.APEX_MODE || 'supervised'];
            if (projectRoot) { args.push('--target', projectRoot); }
        } else if (plan === 'daemon' && extraEnv?.APEX_DAEMON_ACTION) {
            args = ['-m', 'app.cli', 'daemon', extraEnv.APEX_DAEMON_ACTION];
            if (extraEnv.APEX_GOAL) { args.push('--goal', extraEnv.APEX_GOAL); }
            if (extraEnv.APEX_DAEMON_INTERVAL) { args.push('--interval', extraEnv.APEX_DAEMON_INTERVAL); }
            if (projectRoot) { args.push('--target', projectRoot); }
        } else {
            args = ['-m', 'app.main'];
        }

        const child = cp.spawn(pythonPath, args, {
            cwd: apexRoot,
            env,
            shell: true
        });

        let stdout = '';
        child.stdout.on('data', (data) => {
            const chunk = data.toString();
            stdout += chunk;
            outputChannel.append(chunk);
        });

        child.stderr.on('data', (data) => {
            outputChannel.append(data.toString());
        });

        child.on('close', (code) => {
            outputChannel.appendLine(`[Apex] Exit code: ${code}`);
            try {
                const lines = stdout.trim().split('\n');
                const jsonLine = lines.find(l => l.startsWith('{')) || lines[lines.length - 1];
                const parsed = JSON.parse(jsonLine);
                const risks = extractRisks(parsed);
                resolve({ risks });
            } catch {
                resolve(null);
            }
        });
    });
}

function extractRisks(result: any): any[] {
    const risks: any[] = [];
    const report = result?.final_output || result;
    if (!report) return risks;
    
    const branchMap = report.branch_map || {};
    for (const [branch, claim] of Object.entries(branchMap)) {
        risks.push({
            severity: 'info',
            branch,
            claim,
            file: ''
        });
    }
    return risks;
}
