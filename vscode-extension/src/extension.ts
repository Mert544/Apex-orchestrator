import * as vscode from 'vscode';
import { registerCommands } from './commands';
import { ApexResultsProvider } from './treeProvider';
import { ApexDiagnostics } from './diagnostics';

export function activate(context: vscode.ExtensionContext) {
    const outputChannel = vscode.window.createOutputChannel('Apex Orchestrator');
    const treeProvider = new ApexResultsProvider();
    const diagnostics = new ApexDiagnostics();
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    
    statusBar.text = "$(search) Apex";
    statusBar.tooltip = "Run Apex Project Scan";
    statusBar.command = 'apex.projectScan';
    statusBar.show();

    vscode.window.registerTreeDataProvider('apex.scanResults', treeProvider);
    
    registerCommands(context, outputChannel, treeProvider, diagnostics, statusBar);

    context.subscriptions.push(outputChannel, statusBar, diagnostics);
}

export function deactivate() {}
