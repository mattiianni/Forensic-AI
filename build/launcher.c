/*
 * Forensic Tools — launcher nativo (Contents/MacOS/Forensic Tools)
 *
 * 1° avvio: imposta PYTHONHOME e DYLD_FALLBACK_LIBRARY_PATH (letto da dyld solo
 *           all'avvio del processo) e rilancia se stesso con execv.
 * 2° avvio: carica libpython dal runtime incluso ed esegue Py_BytesMain.
 *           Il processo resta l'eseguibile del bundle: nome e icona corretti nel Dock.
 * Senza argomenti propri esegue Resources/app/main.py; con argomenti (sottoprocessi
 * Python, es. multiprocessing o "python -m ...") si comporta come l'interprete.
 *
 * Compilazione: clang -arch arm64 -O2 -mmacosx-version-min=13.0 -o "Forensic Tools" launcher.c
 */
#include <dlfcn.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef int (*py_bytes_main_t)(int, char **);

static void alert(const char *msg) {
    char cmd[PATH_MAX + 256];
    snprintf(cmd, sizeof cmd,
             "/usr/bin/osascript -e 'display alert \"Forensic Tools\" message \"%s\" as critical' >/dev/null 2>&1",
             msg);
    system(cmd);
}

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || !realpath(exe, real)) {
        alert("Impossibile determinare la posizione dell'app.");
        return 1;
    }
    char macos[PATH_MAX], res[PATH_MAX];
    strncpy(macos, dirname(real), sizeof macos);                       /* Contents/MacOS */
    snprintf(res, sizeof res, "%s/../Resources", macos);
    char resolved[PATH_MAX];
    if (realpath(res, resolved)) strncpy(res, resolved, sizeof res);

    char pyhome[PATH_MAX], tools_lib[PATH_MAX], libpy[PATH_MAX], mainpy[PATH_MAX];
    snprintf(pyhome, sizeof pyhome, "%s/runtime/arm64/python", res);
    snprintf(tools_lib, sizeof tools_lib, "%s/runtime/arm64/tools/lib", res);
    snprintf(libpy, sizeof libpy, "%s/lib/libpython3.11.dylib", pyhome);
    snprintf(mainpy, sizeof mainpy, "%s/app/main.py", res);

    if (!getenv("FT_LAUNCHED")) {
        char dyld[PATH_MAX * 2];
        snprintf(dyld, sizeof dyld, "%s:/usr/lib", tools_lib);
        setenv("FT_LAUNCHED", "1", 1);
        setenv("PYTHONHOME", pyhome, 1);
        setenv("DYLD_FALLBACK_LIBRARY_PATH", dyld, 1);
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
        setenv("PYTHONNOUSERSITE", "1", 1);
        unsetenv("PYTHONPATH");
        char *args[] = { real, "-I", mainpy, NULL };   /* scarta -psn_* di LaunchServices */
        execv(real, args);
        alert("Avvio non riuscito (execv).");
        return 1;
    }

    void *h = dlopen(libpy, RTLD_NOW | RTLD_GLOBAL);
    if (!h) { alert("Runtime Python incluso non trovato: reinstalla Forensic Tools."); return 1; }
    py_bytes_main_t py_main = (py_bytes_main_t)dlsym(h, "Py_BytesMain");
    if (!py_main) { alert("Runtime Python non valido."); return 1; }
    return py_main(argc, argv);
}
