import * as vscode from 'vscode';
import { ApexRisk } from './treeProvider';

export class ApexDiagnostics {
    private collection = vscode.languages.createDiagnosticCollection('apex');

    update(risks: ApexRisk[]) {
        const map = new Map<string, vscode.Diagnostic[]>();
        
        for (const risk of risks) {
            if (!risk.file) continue;
            const uri = vscode.Uri.file(risk.file);
            const diag = new vscode.Diagnostic(
                new vscode.Range(0, 0, 0, 0),
                `${risk.branch}: ${risk.claim}`,
                this.severity(risk.severity)
            );
            diag.source = 'Apex';
            const existing = map.get(uri.toString()) || [];
            existing.push(diag);
            map.set(uri.toString(), existing);
        }

        this.collection.clear();
        for (const [uriStr, diags] of map) {
            this.collection.set(vscode.Uri.parse(uriStr), diags);
        }
    }

    clear() {
        this.collection.clear();
    }

    private severity(level: string): vscode.DiagnosticSeverity {
        switch (level) {
            case 'critical': return vscode.DiagnosticSeverity.Error;
            case 'high': return vscode.DiagnosticSeverity.Warning;
            case 'medium': return vscode.DiagnosticSeverity.Information;
            default: return vscode.DiagnosticSeverity.Hint;
        }
    }
}
