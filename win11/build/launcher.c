/*
 * Forensic Tools (Windows 11 Portable) — launcher Win32 GUI (Forensic Tools.exe)
 *
 * - Sottosistema WINDOWS (nessuna finestra console nera all'avvio).
 * - Risolve la cartella portable tramite GetModuleFileNameW (funziona da qualsiasi
 *   cartella o chiavetta USB, anche con spazi nel percorso).
 * - Configura PYTHONHOME, FT_PORTABLE_ROOT, PATH (runtime\python + runtime\tools\bin)
 *   e SetDllDirectoryW.
 * - Carica runtime\python\python311.dll ed esegue Py_Main:
 *     * senza argomenti (doppio clic): avvia "<root>\app\main.py" con "-I"
 *     * con argomenti (es. multiprocessing spawn di ocrmypdf): inoltra argc/argv
 *       mantenendo sys.executable == "Forensic Tools.exe".
 *
 * Compilazione MSVC:
 *   rc /nologo app.rc
 *   cl /nologo /O2 /UNICODE /D_UNICODE launcher.c app.res /link /SUBSYSTEM:WINDOWS shell32.lib user32.lib /OUT:"Forensic Tools.exe"
 *
 * Compilazione MinGW-w64:
 *   windres app.rc -O coff -o app.res
 *   gcc -O2 -municode -mwindows launcher.c app.res -o "Forensic Tools.exe" -lshell32 -luser32
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN

#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

typedef int (__cdecl *py_main_t)(int, wchar_t **);

static void show_error(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"Forensic Tools", MB_OK | MB_ICONERROR);
}

static void dir_of(const wchar_t *path, wchar_t *out, size_t cap) {
    wcsncpy_s(out, cap, path, _TRUNCATE);
    wchar_t *slash = wcsrchr(out, L'\\');
    if (!slash) slash = wcsrchr(out, L'/');
    if (slash) *slash = L'\0';
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, LPWSTR lpCmdLine, int nShow) {
    (void)hInst; (void)hPrev; (void)lpCmdLine; (void)nShow;

    wchar_t exe_path[32768];
    DWORD n = GetModuleFileNameW(NULL, exe_path, (DWORD)(sizeof(exe_path) / sizeof(wchar_t)));
    if (n == 0 || n >= 32768) {
        show_error(L"Impossibile determinare il percorso dell'eseguibile.");
        return 1;
    }

    wchar_t root[32768];
    dir_of(exe_path, root, 32768);

    wchar_t pyhome[32768], tools_bin[32768], dll_path[32768], main_py[32768];
    _snwprintf_s(pyhome, 32768, _TRUNCATE, L"%s\\runtime\\python", root);
    _snwprintf_s(tools_bin, 32768, _TRUNCATE, L"%s\\runtime\\tools\\bin", root);
    _snwprintf_s(dll_path, 32768, _TRUNCATE, L"%s\\python311.dll", pyhome);
    _snwprintf_s(main_py, 32768, _TRUNCATE, L"%s\\app\\main.py", root);

    SetEnvironmentVariableW(L"FT_PORTABLE_ROOT", root);
    SetEnvironmentVariableW(L"PYTHONHOME", pyhome);
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    SetEnvironmentVariableW(L"WEASYPRINT_DLL_DIRECTORIES", tools_bin);

    /* Anteponi tools\bin e python a PATH */
    DWORD old_len = GetEnvironmentVariableW(L"PATH", NULL, 0);
    size_t new_cap = old_len + 65536;
    wchar_t *new_path = (wchar_t *)calloc(new_cap, sizeof(wchar_t));
    if (new_path) {
        _snwprintf_s(new_path, new_cap, _TRUNCATE, L"%s;%s", tools_bin, pyhome);
        if (old_len > 1) {
            size_t cur = wcslen(new_path);
            new_path[cur++] = L';';
            GetEnvironmentVariableW(L"PATH", new_path + cur, (DWORD)(new_cap - cur));
        }
        SetEnvironmentVariableW(L"PATH", new_path);
        free(new_path);
    }

    SetDllDirectoryW(pyhome);

    HMODULE hPy = LoadLibraryW(dll_path);
    if (!hPy) {
        show_error(L"Runtime Python (python311.dll) non trovato.\nVerifica che la cartella runtime\\python esista accanto a Forensic Tools.exe.");
        return 1;
    }

    py_main_t py_main = (py_main_t)GetProcAddress(hPy, "Py_Main");
    if (!py_main) {
        show_error(L"Runtime Python non valido (Py_Main mancante).");
        return 1;
    }

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv || argc <= 1) {
        wchar_t *default_args[] = { exe_path, L"-I", main_py, NULL };
        int rc = py_main(3, default_args);
        if (argv) LocalFree(argv);
        return rc;
    }

    /* Sottoprocesso Python (es. multiprocessing spawn di ocrmypdf) */
    int rc = py_main(argc, argv);
    LocalFree(argv);
    return rc;
}
